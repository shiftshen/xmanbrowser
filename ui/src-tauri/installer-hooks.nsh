; NSIS installer hooks for XmanBrowser.
; The app spawns a backend sidecar (xman-server.exe) that keeps the bundled
; PyInstaller _internal/*.pyd files open. Tauri's installer closes the main app
; but not that child, so an upgrade hits "Error opening file for writing".
; Kill the sidecar (and the app) before copying files.

!macro NSIS_HOOK_PREINSTALL
  nsExec::Exec 'taskkill /F /T /IM xman-server.exe'
  nsExec::Exec 'taskkill /F /T /IM XmanBrowser.exe'
  Sleep 1000
!macroend
