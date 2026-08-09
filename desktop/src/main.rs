#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::time::Duration;
use tauri::{Manager, Emitter};
use tokio::process::{Command, Child};
use std::sync::Arc;
use tokio::sync::Mutex;
use serde_json::Value;

#[derive(Clone, serde::Serialize)]
struct StatusPayload {
    message: String,
}

#[derive(Clone, serde::Serialize)]
struct ErrorPayload {
    error: String,
}

#[derive(Clone, serde::Serialize)]
struct ReadyPayload {
    url: String,
}

struct AppState {
    children: Arc<Mutex<Vec<Child>>>,
}

async fn run_boot_sequence(app: tauri::AppHandle, state: Arc<AppState>) -> anyhow::Result<()> {
    let emit_status = |msg: &str| {
        println!("[BOOT] {}", msg);
        let _ = app.emit("boot-status", StatusPayload { message: msg.to_string() });
    };

    emit_status("Setting up directories...");
    
    // Detect if we're running inside a Flatpak container
    let is_flatpak = std::env::var("FLATPAK_ID").is_ok();
    
    let current_dir = std::env::current_dir()?;
    
    let (src_dir, venv_python, redis_bin, celery_bin, data_dir) = if is_flatpak {
        let xdg_data_home = std::env::var("XDG_DATA_HOME").unwrap_or_else(|_| format!("{}/.var/app/io.github.dannyvfilms.Floppy/data", std::env::var("HOME").unwrap_or_default()));
        (
            std::path::PathBuf::from("/app/share/floppy/src"),
            std::path::PathBuf::from("/app/bin/python"),
            "redis-server".to_string(), // Installed to /app/bin which is in PATH
            std::path::PathBuf::from("/app/bin/celery"),
            std::path::PathBuf::from(xdg_data_home)
        )
    } else {
        (
            current_dir.join("../Floppy/.worktrees/native-fedora-support/src"),
            current_dir.join("../Floppy/venv/bin/python"),
            "redis-server".to_string(),
            current_dir.join("../Floppy/venv/bin/celery"),
            current_dir.join("../Floppy/db")
        )
    }; 
    let redis_sock = data_dir.join("redis.sock");
    
    std::env::set_var("SECRET", "1"); // For dev
    std::env::set_var("FLOPPY_DATA_DIR", data_dir.to_string_lossy().to_string());
    std::env::set_var("REDIS_URL", format!("unix://{}?db=0", redis_sock.to_string_lossy()));
    std::env::set_var("CELERY_BROKER_URL", format!("redis+socket://{}", redis_sock.to_string_lossy()));
    std::env::set_var("CELERY_RESULT_BACKEND", format!("redis+socket://{}", redis_sock.to_string_lossy()));
    std::env::set_var("FLOPPY_RESOURCE_TIER", "minimal");

    emit_status("Running preflight checks...");
    let preflight_output = Command::new(&venv_python)
        .current_dir(&src_dir)
        .arg("manage.py")
        .arg("floppy_preflight")
        .arg("--json")
        .output()
        .await?;

    if !preflight_output.status.success() {
        let stderr = String::from_utf8_lossy(&preflight_output.stderr);
        anyhow::bail!("Preflight failed: {}", stderr);
    }

    let preflight_str = String::from_utf8_lossy(&preflight_output.stdout);
    let preflight_data: Value = serde_json::from_str(&preflight_str).unwrap_or_default();

    let integrity_ok = preflight_data["integrity_ok"].as_bool().unwrap_or(false);
    if !integrity_ok {
        let err = preflight_data["integrity_error"].as_str().unwrap_or("Unknown error");
        anyhow::bail!("Database integrity check failed: {}", err);
    }

    let needs_migration = preflight_data["needs_migration"].as_bool().unwrap_or(false);
    if needs_migration {
        emit_status("Running database migrations...");
        let migrate_status = Command::new(&venv_python)
            .current_dir(&src_dir)
            .arg("manage.py")
            .arg("migrate")
            .status()
            .await?;
        if !migrate_status.success() {
            anyhow::bail!("Migrations failed");
        }
    }

    emit_status("Starting Redis...");
    let redis_child = Command::new(redis_bin)
        .arg("--port")
        .arg("0")
        .arg("--unixsocket")
        .arg(&redis_sock)
        .arg("--unixsocketperm")
        .arg("700")
        .spawn()?;
    state.children.lock().await.push(redis_child);

    tokio::time::sleep(Duration::from_millis(500)).await;

    emit_status("Starting Web Server...");
    let web_server_child = Command::new(&venv_python)
        .current_dir(&src_dir)
        .arg("manage.py")
        .arg("runserver")
        .arg("127.0.0.1:18181")
        .arg("--noreload")
        .arg("--insecure")
        .spawn()?;
    state.children.lock().await.push(web_server_child);

    emit_status("Starting Background Workers...");
    // PYTHONPATH is needed for celery to find the config module
    let mut celery_cmd = Command::new(&celery_bin);
    celery_cmd.current_dir(&src_dir)
        .env("PYTHONPATH", &src_dir)
        .arg("-A")
        .arg("config")
        .arg("worker")
        .arg("--beat")
        .arg("--scheduler")
        .arg("django")
        .arg("--concurrency")
        .arg("1");
    let celery_child = celery_cmd.spawn()?;
    state.children.lock().await.push(celery_child);

    emit_status("Waiting for Floppy to become ready...");
    let client = reqwest::Client::new();
    let target_url = "http://127.0.0.1:18181";
    let ping_url = format!("{}/ping/", target_url);
    
    let mut ready = false;
    for _ in 0..60 {
        if let Ok(resp) = client.get(&ping_url).send().await {
            if resp.status().is_success() {
                ready = true;
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    if !ready {
        anyhow::bail!("Timed out waiting for web server to become ready");
    }

    emit_status("Ready!");
    let _ = app.emit("server-ready", ReadyPayload { url: target_url.to_string() });

    Ok(())
}

fn main() {
    // Disable WebKit DMA-BUF renderer on Linux to prevent Mesa aborts on Wayland without losing HW acceleration
    std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    std::env::set_var("WEBKIT_DISABLE_COMPOSITING_MODE", "1");
    
    env_logger::init();
    
    let app_state = Arc::new(AppState {
        children: Arc::new(Mutex::new(Vec::new())),
    });
    
    let app_state_clone = app_state.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, argv, cwd| {
            println!("{}, {argv:?}, {cwd}", app.package_info().name);
        }))
        .setup(move |app| {
            let handle = app.handle().clone();
            let state = app_state_clone.clone();
            
            tauri::async_runtime::spawn(async move {
                if let Err(e) = run_boot_sequence(handle.clone(), state).await {
                    println!("[BOOT ERROR] {}", e);
                    let _ = handle.emit("boot-error", ErrorPayload { error: e.to_string() });
                }
            });
            
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while running tauri application")
        .run(move |_app_handle, event| match event {
            tauri::RunEvent::ExitRequested { .. } => {
                println!("Exit requested, cleaning up...");
                let mut children = tauri::async_runtime::block_on(async {
                    app_state.children.lock().await
                });
                for mut child in children.drain(..) {
                    let _ = child.kill();
                    let _ = tauri::async_runtime::block_on(child.wait());
                }
            }
            _ => {}
        });
}
