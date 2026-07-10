use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use rand::{distributions::Alphanumeric, Rng};
use tauri::Manager;
#[cfg(debug_assertions)]
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
#[cfg(debug_assertions)]
use tauri_plugin_shell::ShellExt;

// Dev uses the source-backed shell sidecar via externalBin (no rebuild needed).
// Release ships the PyInstaller --onedir tree (exe + _internal/) as a Tauri
// resource and spawns the inner exe directly: onedir skips the per-launch onefile
// self-extraction, so the sidecar reaches ready in a fraction of the time.
const SIDECAR_NAME: &str = if cfg!(debug_assertions) {
    "video-intake-fastapi-sidecar-dev"
} else {
    "video-intake-fastapi-sidecar"
};

// Release: subdir under resource_dir() that holds the onedir tree. Must match the
// bundle.resources target in tauri.conf.json.
#[cfg(not(debug_assertions))]
const SIDECAR_RESOURCE_DIR: &str = "sidecar";

// Must match backend/sidecar_main.py VIDEO_INTAKE_FASTAPI_PORT default.
const SIDECAR_PORT: u16 = 8766;

// Dev holds the shell plugin's CommandChild; release holds the std::process child
// of the directly-spawned onedir exe. Reaping is by recorded PID either way, so the
// handle only serves precise kill of our own child (exit / pre-update).
#[cfg(debug_assertions)]
type SidecarChild = CommandChild;
#[cfg(not(debug_assertions))]
type SidecarChild = std::process::Child;

/// Tracks whether the bundled FastAPI sidecar has reported readiness.
#[derive(Default)]
struct SidecarState {
    ready: AtomicBool,
}

/// Keeps the spawned sidecar child alive for the app lifetime.
struct SidecarProcess(#[allow(dead_code)] Mutex<Option<SidecarChild>>);

/// Per-launch bearer token shared only between the Tauri webview and sidecar.
struct SidecarSession {
    token: String,
}

#[tauri::command]
fn sidecar_ready(state: tauri::State<'_, Arc<SidecarState>>) -> bool {
    state.ready.load(Ordering::Relaxed)
}

#[tauri::command]
fn sidecar_session_token(session: tauri::State<'_, Arc<SidecarSession>>) -> String {
    session.token.clone()
}

fn generate_session_token() -> String {
    rand::thread_rng()
        .sample_iter(&Alphanumeric)
        .take(48)
        .map(char::from)
        .collect()
}

// Sidecar ownership (P0): a previous run's sidecar can outlive the app (crash /
// forced-quit skips the exit handler) and squat the fixed port. We reap it
// SELECTIVELY — only the PID *we* recorded, and only if it is still one of our
// sidecars (name-verified) — instead of blunt-killing anything on the port / any
// process of that name, which risked killing unrelated processes.
fn sidecar_pid_path(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    app.path().app_local_data_dir().ok().map(|d| d.join("sidecar.pid"))
}

fn record_sidecar_pid(app: &tauri::AppHandle, pid: u32) {
    if let Some(path) = sidecar_pid_path(app) {
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&path, pid.to_string());
    }
}

fn clear_sidecar_pid(app: &tauri::AppHandle) {
    if let Some(path) = sidecar_pid_path(app) {
        let _ = std::fs::remove_file(path);
    }
}

/// True iff a live process with `pid` is one of our sidecars. The name check
/// guards against PID reuse: a recycled PID belonging to an unrelated process
/// must never be killed.
#[cfg(unix)]
fn is_our_sidecar(pid: u32) -> bool {
    std::process::Command::new("ps")
        .args(["-p", &pid.to_string(), "-o", "comm="])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("video-intake"))
        .unwrap_or(false)
}

#[cfg(not(unix))]
fn is_our_sidecar(pid: u32) -> bool {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    std::process::Command::new("tasklist")
        .args(["/FI", &format!("PID eq {pid}"), "/NH", "/FO", "CSV"])
        .creation_flags(CREATE_NO_WINDOW)
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("video-intake-fastapi-sidecar"))
        .unwrap_or(false)
}

#[cfg(unix)]
fn kill_pid(pid: u32) {
    let _ = std::process::Command::new("kill").args(["-9", &pid.to_string()]).status();
}

#[cfg(not(unix))]
fn kill_pid(pid: u32) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = std::process::Command::new("taskkill")
        .args(["/F", "/PID", &pid.to_string(), "/T"])
        .creation_flags(CREATE_NO_WINDOW)
        .status();
}

/// PIDs listening on `port`. Used only as reap candidates — every candidate is
/// still name-verified via `is_our_sidecar` before any kill.
#[cfg(unix)]
fn port_listener_pids(port: u16) -> Vec<u32> {
    std::process::Command::new("lsof")
        .args(["-ti", &format!("tcp:{port}"), "-sTCP:LISTEN"])
        .output()
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .lines()
                .filter_map(|line| line.trim().parse().ok())
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(not(unix))]
fn port_listener_pids(port: u16) -> Vec<u32> {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let Ok(output) = std::process::Command::new("netstat")
        .args(["-ano", "-p", "tcp"])
        .creation_flags(CREATE_NO_WINDOW)
        .output()
    else {
        return Vec::new();
    };
    // Column boundary space after ":{port}" keeps :8766 from matching :87661.
    let needle = format!(":{port} ");
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| line.contains("LISTENING") && line.contains(&needle))
        .filter_map(|line| line.split_whitespace().last()?.parse().ok())
        .collect()
}

/// Before spawning ours, kill ONLY a leftover sidecar we recorded last run
/// (name-verified against PID reuse). Never touches an unrelated process.
fn reap_previous_sidecar(app: &tauri::AppHandle) {
    if let Some(path) = sidecar_pid_path(app) {
        if let Ok(text) = std::fs::read_to_string(&path) {
            if let Ok(pid) = text.trim().parse::<u32>() {
                if is_our_sidecar(pid) {
                    log::info!("[sidecar] reaping leftover sidecar pid {pid}");
                    kill_pid(pid);
                    std::thread::sleep(std::time::Duration::from_millis(300));
                }
            }
        }
        let _ = std::fs::remove_file(&path);
    }
    // P0#2 Mac field failure (2026-07-05): an orphan whose pid escaped the file
    // (pid file overwritten by a later spawn while the old sidecar survived a
    // forced-quit) squats the fixed port with a stale session token — every
    // request 401s and the install looks broken. Sweep the port too; the
    // is_our_sidecar name check still guarantees no unrelated process is killed.
    for pid in port_listener_pids(SIDECAR_PORT) {
        if is_our_sidecar(pid) {
            log::warn!("[sidecar] reaping port-squatting orphan sidecar pid {pid}");
            kill_pid(pid);
            std::thread::sleep(std::time::Duration::from_millis(300));
        }
    }
}

/// Kill an owned child handle. Dev's CommandChild::kill consumes self; release's
/// std::process child needs &mut plus a wait() so it doesn't linger as a zombie
/// before a respawn.
#[cfg(debug_assertions)]
fn kill_child(child: SidecarChild) {
    let _ = child.kill();
}
#[cfg(not(debug_assertions))]
fn kill_child(mut child: SidecarChild) {
    let _ = child.kill();
    let _ = child.wait();
}

/// Record our own pid and stash the child so exit / pre-update can kill precisely.
/// First spawn → manage; respawn (update-failure recovery) → the type is already
/// managed and manage() won't overwrite, so slot the new child into the Mutex.
fn store_sidecar_child(app: &tauri::AppHandle, pid: u32, child: SidecarChild) {
    record_sidecar_pid(app, pid);
    if let Some(process) = app.try_state::<SidecarProcess>() {
        if let Ok(mut guard) = process.0.lock() {
            *guard = Some(child);
        }
    } else {
        app.manage(SidecarProcess(Mutex::new(Some(child))));
    }
}

/// Readiness + log forwarding, shared by the dev async event loop and the release
/// stdout reader thread. Uvicorn prints these on both stdout and stderr depending
/// on config; either marks the backend ready.
fn note_sidecar_line(state: &SidecarState, line: &str) {
    if line.contains("Application startup complete") || line.contains("Uvicorn running") {
        state.ready.store(true, Ordering::Relaxed);
    }
    log::info!("[sidecar] {}", line.trim_end());
}

/// Kill the sidecar we currently manage (used before an in-app update so the
/// installer can overwrite the locked binary). Precise by construction — it is
/// our own child handle, not a port/name sweep.
fn kill_current_sidecar(app: &tauri::AppHandle) {
    if let Some(process) = app.try_state::<SidecarProcess>() {
        if let Some(child) = process.0.lock().ok().and_then(|mut g| g.take()) {
            kill_child(child);
        }
    }
    clear_sidecar_pid(app);
    std::thread::sleep(std::time::Duration::from_millis(300));
}

/// Re-launch the sidecar (P0 #3): used when an in-app update is aborted after we
/// already killed the running sidecar, so the app keeps a working backend for the
/// current session instead of being dead until the user manually restarts.
fn respawn_sidecar(app: &tauri::AppHandle) {
    if let (Some(state), Some(session)) = (
        app.try_state::<Arc<SidecarState>>(),
        app.try_state::<Arc<SidecarSession>>(),
    ) {
        spawn_sidecar(app, state.inner().clone(), session.inner().clone());
    }
}

fn recover_on_error<T, E>(result: Result<T, E>, recover: impl FnOnce()) -> Result<T, E> {
    if result.is_err() {
        recover();
    }
    result
}

/// Dev: spawn the source-backed shell sidecar via the shell plugin's externalBin
/// resolution, forwarding its event stream to the shared readiness/log helper.
#[cfg(debug_assertions)]
fn spawn_sidecar(app: &tauri::AppHandle, state: Arc<SidecarState>, session: Arc<SidecarSession>) {
    reap_previous_sidecar(app);
    let command = match app.shell().sidecar(SIDECAR_NAME) {
        Ok(command) => command,
        Err(err) => {
            log::error!("[sidecar] failed to resolve {SIDECAR_NAME}: {err}");
            return;
        }
    };
    let command = command.env("YT_NOTE_APP_SESSION_TOKEN", session.token.clone());
    let (mut rx, child) = match command.spawn() {
        Ok(pair) => pair,
        Err(err) => {
            log::error!("[sidecar] failed to spawn {SIDECAR_NAME}: {err}");
            return;
        }
    };
    store_sidecar_child(app, child.pid(), child);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(bytes) | CommandEvent::Stderr(bytes) => {
                    note_sidecar_line(&state, &String::from_utf8_lossy(&bytes));
                }
                CommandEvent::Terminated(payload) => {
                    state.ready.store(false, Ordering::Relaxed);
                    log::warn!("[sidecar] terminated: {payload:?}");
                }
                CommandEvent::Error(err) => log::error!("[sidecar] error: {err}"),
                _ => {}
            }
        }
    });
}

/// Release: locate the onedir tree under resource_dir() and return the inner exe.
/// The exe and its _internal/ sibling must keep their relative layout, which the
/// bundle.resources copy preserves.
#[cfg(not(debug_assertions))]
fn resolve_sidecar_exe(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    let base = app.path().resource_dir().ok()?.join(SIDECAR_RESOURCE_DIR);
    let exe_name = format!("{SIDECAR_NAME}{}", std::env::consts::EXE_SUFFIX);
    // Tauri's dir-resource copy has historically either flattened the contents into
    // the target dir or nested them under the source folder name; accept both so a
    // bundler-version change can't silently break the spawn.
    for candidate in [base.join(&exe_name), base.join(SIDECAR_NAME).join(&exe_name)] {
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    log::error!("[sidecar] onedir exe not found under {base:?}");
    None
}

/// Release: directly spawn the onedir exe (no per-launch self-extraction), piping
/// its output into reader threads that drive readiness + log forwarding. Spawning
/// via std::process is intentional — like open_log_dir, it is not gated by the
/// shell capability scope, which cannot statically express a per-machine resource
/// path. Reaping stays precise: it uses the recorded pid, name-verified.
#[cfg(not(debug_assertions))]
fn spawn_sidecar(app: &tauri::AppHandle, state: Arc<SidecarState>, session: Arc<SidecarSession>) {
    use std::io::{BufRead, BufReader};
    use std::process::{Command, Stdio};

    reap_previous_sidecar(app);
    let Some(exe) = resolve_sidecar_exe(app) else {
        return;
    };
    let mut child = match Command::new(&exe)
        .env("YT_NOTE_APP_SESSION_TOKEN", session.token.clone())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(err) => {
            log::error!("[sidecar] failed to spawn {exe:?}: {err}");
            return;
        }
    };
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    store_sidecar_child(app, child.id(), child);

    // Uvicorn's readiness lines can land on either stream. stdout EOF marks the
    // process gone (mirrors the dev Terminated event); stderr just forwards.
    if let Some(out) = stdout {
        let state = state.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                note_sidecar_line(&state, &line);
            }
            state.ready.store(false, Ordering::Relaxed);
            log::warn!("[sidecar] stdout closed (terminated)");
        });
    }
    if let Some(err) = stderr {
        let state = state.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                note_sidecar_line(&state, &line);
            }
        });
    }
}


/// In-app update against the private GitHub repo. The frontend resolves the
/// latest release and passes the latest.json ASSET API url + the user's
/// read-only token (stored locally, never embedded in the binary); this
/// command verifies the minisign signature, installs, then restarts.
#[tauri::command]
async fn install_app_update(app: tauri::AppHandle, endpoint: String, token: String) -> Result<String, String> {
    use tauri_plugin_updater::UpdaterExt;

    // token 選填（S2 公開化）：私有 repo 帶 Bearer；公開 repo 匿名抓 release assets
    let mut builder = app
        .updater_builder()
        .endpoints(vec![endpoint.parse().map_err(|e| format!("endpoint: {e}"))?])
        .map_err(|e| e.to_string())?;
    if !token.trim().is_empty() {
        builder = builder
            .header("Authorization", format!("Bearer {}", token.trim()))
            .map_err(|e| e.to_string())?;
    }
    let updater = builder
        .header("Accept", "application/octet-stream")
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())?;
    let update = updater
        .check()
        .await
        .map_err(|e| e.to_string())?
        .ok_or_else(|| "already up to date".to_string())?;
    log::info!("installing update {}", update.version);
    // 安裝前先放掉自己的 sidecar：否則 Windows 安裝程式覆寫 video-intake-fastapi-sidecar.exe
    // 時檔案被鎖（"Error opening file for writing"），更新整個卡死。精準殺自己的 child（非埠/名掃）。
    kill_current_sidecar(&app);
    // 安裝失敗（下載/簽章/網路）→ 把剛殺掉的 sidecar 重新拉起，App 當次不致失去後端（P0 #3）。
    let install_result = update.download_and_install(|_, _| {}, || {}).await;
    if let Err(e) = recover_on_error(install_result, || respawn_sidecar(&app)) {
        log::warn!("[update] install failed, respawning sidecar: {e}");
        return Err(e.to_string());
    }
    app.restart()
}

/// Open the OS log directory (where tauri-plugin-log's LogDir target writes) in
/// the native file manager, so JY can hand the log file back into the chat when a
/// packaged build misbehaves. Rust-side Command is intentional: it is not gated by
/// the shell capability scope and needs no extra permission entry.
#[tauri::command]
fn open_log_dir(app: tauri::AppHandle) -> Result<(), String> {
    let dir = app.path().app_log_dir().map_err(|e| e.to_string())?;
    let _ = std::fs::create_dir_all(&dir);
    #[cfg(target_os = "macos")]
    let program = "open";
    #[cfg(target_os = "windows")]
    let program = "explorer";
    #[cfg(all(unix, not(target_os = "macos")))]
    let program = "xdg-open";
    std::process::Command::new(program)
        .arg(&dir)
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  // Production diagnostics: route Rust panics into the log facade so a packaged
  // build records the crash cause in the same file (panics otherwise hit only
  // stderr, which a windowed release discards). Chain the default hook to keep
  // dev's stderr backtrace.
  let default_panic = std::panic::take_hook();
  std::panic::set_hook(Box::new(move |info| {
    log::error!("[panic] {info}");
    default_panic(info);
  }));
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .plugin(tauri_plugin_dialog::init())
    .plugin(tauri_plugin_updater::Builder::new().build())
    .invoke_handler(tauri::generate_handler![sidecar_ready, sidecar_session_token, install_app_update, open_log_dir])
    .setup(|app| {
      // Register file logging in BOTH dev and release. Previously this was
      // dev-only, so release builds dropped every log::* call (sidecar
      // termination, update failure, the forwarded Python sidecar stdout) into
      // the void. Default targets are Stdout + LogDir; the plugin's default
      // max_file_size is only 40 KB, so raise it — 5 MB with the default KeepOne
      // rotation caps the footprint at ~10 MB. A logging-init failure must never
      // block app startup.
      if let Err(err) = app.handle().plugin(
        tauri_plugin_log::Builder::default()
          .level(log::LevelFilter::Info)
          .max_file_size(5_000_000)
          .build(),
      ) {
        eprintln!("[log] failed to initialise logging: {err}");
      }
      let state = Arc::new(SidecarState::default());
      let session = Arc::new(SidecarSession { token: generate_session_token() });
      app.manage(state.clone());
      app.manage(session.clone());
      spawn_sidecar(&app.handle().clone(), state, session);
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app_handle, event| {
      if let tauri::RunEvent::Exit = event {
        if let Some(process) = app_handle.try_state::<SidecarProcess>() {
          if let Some(child) = process.0.lock().ok().and_then(|mut guard| guard.take()) {
            kill_child(child);
          }
        }
        clear_sidecar_pid(app_handle);
      }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn unrelated_process_is_not_owned_sidecar() {
        #[cfg(unix)]
        let mut child = std::process::Command::new("sleep")
            .arg("5")
            .spawn()
            .expect("spawn unrelated fixture process");
        #[cfg(windows)]
        let mut child = std::process::Command::new("powershell")
            .args(["-NoProfile", "-Command", "Start-Sleep -Seconds 5"])
            .spawn()
            .expect("spawn unrelated fixture process");

        assert!(!is_our_sidecar(child.id()));
        assert!(child.try_wait().expect("query fixture process").is_none());

        let _ = child.kill();
        let _ = child.wait();
    }

    #[test]
    fn port_listener_pids_finds_our_listener_and_name_check_blocks_kill() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").expect("bind ephemeral port");
        let port = listener.local_addr().expect("local addr").port();

        let pids = port_listener_pids(port);
        assert!(
            pids.contains(&std::process::id()),
            "expected own pid {} among listeners {:?} on port {}",
            std::process::id(),
            pids,
            port
        );
        // The squatter sweep must still refuse to kill: this test process is a
        // listener on the port but is not a name-verified sidecar.
        assert!(!is_our_sidecar(std::process::id()));
    }

    #[test]
    fn update_failure_runs_recovery_once_and_preserves_error() {
        let recoveries = AtomicUsize::new(0);
        let result: Result<(), &str> = recover_on_error(Err("signature failure"), || {
            recoveries.fetch_add(1, Ordering::Relaxed);
        });

        assert_eq!(result, Err("signature failure"));
        assert_eq!(recoveries.load(Ordering::Relaxed), 1);
    }

    #[test]
    fn successful_update_does_not_run_recovery() {
        let recoveries = AtomicUsize::new(0);
        let result: Result<&str, &str> = recover_on_error(Ok("installed"), || {
            recoveries.fetch_add(1, Ordering::Relaxed);
        });

        assert_eq!(result, Ok("installed"));
        assert_eq!(recoveries.load(Ordering::Relaxed), 0);
    }
}
