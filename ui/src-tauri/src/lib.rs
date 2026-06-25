// XMan desktop shell. On startup it launches the local Python control service
// (FastAPI) as a child process and shuts it down when the app exits, so the user
// gets a single-click experience. If the backend can't be started here (e.g. a
// packaged build without the dev venv), the UI still loads and simply shows
// "API offline" until `xman serve` is run manually.

use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

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
