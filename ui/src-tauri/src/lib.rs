// XMan desktop shell. On startup it launches the local Python control service
// (FastAPI) as a child process and shuts it down when the app exits, so the user
// gets a single-click experience. If the backend can't be started here (e.g. a
// packaged build without the dev venv), the UI still loads and simply shows
// "API offline" until `xman serve` is run manually.

use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

/// The local control API port (must match the Python default in `xman.cli serve`
/// / `sidecar_main`). The desktop shell owns this port.
const API_PORT: u16 = 8723;

/// Kill a stale `xman-server` that's still holding the API port from a previous
/// run that didn't exit cleanly (crash, force-quit, or an older app version left
/// running). Without this, our freshly-spawned sidecar can't bind the port, so
/// the UI silently connects to the OLD backend — meaning bug-fixes in a new build
/// don't take effect (a fixed app served by a stale buggy sidecar). Best-effort
/// and name-checked so we never kill an unrelated process that happens to use the
/// port. The per-profile browser runners don't listen on this port, so they're
/// untouched.
fn free_api_port() {
    for pid in listeners_on_port(API_PORT) {
        if process_is_sidecar(&pid) {
            log::info!("killing stale backend holding port {API_PORT} (pid {pid})");
            kill_pid(&pid);
        }
    }
}

#[cfg(unix)]
fn listeners_on_port(port: u16) -> Vec<String> {
    Command::new("lsof")
        .args(["-ti", &format!("tcp:{port}"), "-sTCP:LISTEN"])
        .output()
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .split_whitespace()
                .map(|s| s.to_string())
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(windows)]
fn listeners_on_port(port: u16) -> Vec<String> {
    let needle = format!(":{port}");
    hidden_command("netstat")
        .args(["-ano", "-p", "tcp"])
        .output()
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .lines()
                .filter(|l| l.contains(&needle) && l.to_uppercase().contains("LISTENING"))
                .filter_map(|l| l.split_whitespace().last().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(unix)]
fn process_is_sidecar(pid: &str) -> bool {
    Command::new("ps")
        .args(["-p", pid, "-o", "comm="])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("xman-server"))
        .unwrap_or(false)
}

#[cfg(windows)]
fn process_is_sidecar(pid: &str) -> bool {
    hidden_command("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/NH"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("xman-server"))
        .unwrap_or(false)
}

#[cfg(unix)]
fn kill_pid(pid: &str) {
    let _ = Command::new("kill").args(["-9", pid]).status();
}

#[cfg(windows)]
fn kill_pid(pid: &str) {
    let _ = hidden_command("taskkill").args(["/F", "/PID", pid]).status();
}

/// Build a Command that never flashes a console window. The PyInstaller sidecar
/// is a console subsystem exe, so on Windows spawning it would pop a black cmd
/// window next to the app; CREATE_NO_WINDOW suppresses it (no-op elsewhere).
fn hidden_command<S: AsRef<std::ffi::OsStr>>(program: S) -> Command {
    let cmd = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        let mut cmd = cmd;
        cmd.creation_flags(CREATE_NO_WINDOW);
        return cmd;
    }
    #[cfg(not(windows))]
    cmd
}

fn spawn_backend(resource_dir: Option<std::path::PathBuf>) -> Option<Child> {
    // Reap any stale backend from a previous run that didn't shut down cleanly,
    // so our sidecar can bind the port instead of the UI talking to the old one.
    free_api_port();

    // 1. Bundled sidecar (production): a PyInstaller onedir backend shipped under
    //    the app's resources (sidecar/xman-server + sidecar/_internal/). onedir
    //    means no per-launch self-extraction → ~1s cold start. No Python needed.
    if let Some(res) = resource_dir {
        let name = if cfg!(windows) { "xman-server.exe" } else { "xman-server" };
        let sidecar = res.join("sidecar").join(name);
        if sidecar.exists() {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                if let Ok(meta) = std::fs::metadata(&sidecar) {
                    let mut p = meta.permissions();
                    if p.mode() & 0o111 == 0 {
                        p.set_mode(0o755);
                        let _ = std::fs::set_permissions(&sidecar, p);
                    }
                }
            }
            match hidden_command(&sidecar).spawn() {
                Ok(child) => {
                    log::info!("started bundled sidecar (pid {})", child.id());
                    return Some(child);
                }
                Err(e) => log::error!("sidecar spawn failed: {e}"),
            }
        }
    }

    // 2. Dev virtualenv next to the Python package. CARGO_MANIFEST_DIR is
    //    .../app/ui/src-tauri at compile time; the app root is two levels up.
    let manifest = env!("CARGO_MANIFEST_DIR");
    let app_dir = std::path::Path::new(manifest)
        .parent()
        .and_then(|p| p.parent())
        .map(|p| p.to_path_buf());

    if let Some(dir) = &app_dir {
        // venv layout differs: POSIX => .venv/bin/python, Windows => .venv/Scripts/python.exe
        let py = if cfg!(windows) {
            dir.join(".venv").join("Scripts").join("python.exe")
        } else {
            dir.join(".venv").join("bin").join("python")
        };
        if py.exists() {
            match hidden_command(&py)
                .args(["-m", "xman.cli", "serve"])
                .current_dir(dir)
                .spawn()
            {
                Ok(child) => {
                    log::info!("started backend: {} (pid {})", py.display(), child.id());
                    return Some(child);
                }
                Err(e) => log::error!("failed to start venv backend: {e}"),
            }
        }
    }

    // Fallback: rely on `xman` being on PATH.
    match hidden_command("xman").arg("serve").spawn() {
        Ok(child) => {
            log::info!("started backend via PATH `xman serve` (pid {})", child.id());
            Some(child)
        }
        Err(e) => {
            log::warn!("no backend started ({e}); run `xman serve` manually");
            None
        }
    }
}

/// Write UTF-8 text to an absolute path the user picked via the save dialog.
/// Doing the write in Rust avoids the webview's unreliable blob download and the
/// fs-plugin scope dance; the path comes from the native dialog, not the page.
#[tauri::command]
fn save_text(path: String, contents: String) -> Result<(), String> {
    std::fs::write(&path, contents).map_err(|e| e.to_string())
}

/// Read UTF-8 text from a path the user picked via the open dialog.
#[tauri::command]
fn read_text(path: String) -> Result<String, String> {
    std::fs::read_to_string(&path).map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .invoke_handler(tauri::generate_handler![save_text, read_text])
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .setup(|app| {
            let res = app.path().resource_dir().ok();
            app.manage(Backend(Mutex::new(spawn_backend(res))));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { .. } = event {
            if let Some(state) = app_handle.try_state::<Backend>() {
                if let Some(mut child) = state.0.lock().unwrap().take() {
                    log::info!("stopping backend (pid {})", child.id());
                    let _ = child.kill();
                }
            }
        }
    });
}
