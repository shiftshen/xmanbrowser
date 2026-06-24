// XMan desktop shell. On startup it launches the local Python control service
// (FastAPI) as a child process and shuts it down when the app exits, so the user
// gets a single-click experience. If the backend can't be started here (e.g. a
// packaged build without the dev venv), the UI still loads and simply shows
// "API offline" until `xman serve` is run manually.

use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct Backend(Mutex<Option<Child>>);

fn spawn_backend() -> Option<Child> {
    // 1. Bundled sidecar (production): a standalone backend executable placed
    //    next to the app binary via Tauri externalBin. No Python needed.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let name = if cfg!(windows) { "xman-server.exe" } else { "xman-server" };
            let sidecar = dir.join(name);
            if sidecar.exists() {
                match Command::new(&sidecar).spawn() {
                    Ok(child) => {
                        log::info!("started bundled sidecar (pid {})", child.id());
                        return Some(child);
                    }
                    Err(e) => log::error!("sidecar spawn failed: {e}"),
                }
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
            match Command::new(&py)
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
    match Command::new("xman").arg("serve").spawn() {
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(
            tauri_plugin_log::Builder::default()
                .level(log::LevelFilter::Info)
                .build(),
        )
        .setup(|app| {
            app.manage(Backend(Mutex::new(spawn_backend())));
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
