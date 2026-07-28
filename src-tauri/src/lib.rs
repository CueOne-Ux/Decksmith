use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};

#[derive(Default)]
struct ScanState {
    cancel_file: Mutex<Option<PathBuf>>,
}

#[derive(Default)]
struct AnalysisState {
    cancel_file: Mutex<Option<PathBuf>>,
}

#[derive(Default)]
struct StemState {
    cancel_file: Mutex<Option<PathBuf>>,
}

#[derive(Default)]
struct RenderState {
    cancel_file: Mutex<Option<PathBuf>>,
}

fn project_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri must be inside the project root")
        .to_path_buf()
}

fn database_path(app: &AppHandle) -> Result<PathBuf, String> {
    let directory = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
    Ok(directory.join("decksmith.db"))
}

fn backend_command(app: &AppHandle) -> Result<Command, String> {
    if cfg!(debug_assertions) {
        let root = project_root();
        let python = root.join(".venv/bin/python");
        if !python.exists() {
            return Err(
                "Decksmith's local service is missing. Run the project setup first.".into(),
            );
        }
        let mut command = Command::new(python);
        command
            .current_dir(&root)
            .env("PYTHONPATH", root.join("backend"))
            .arg("-m")
            .arg("decksmith.cli");
        return Ok(command);
    }

    let resources = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Could not locate Decksmith's local service: {error}"))?;
    let executable = resources
        .join("backend-runtime")
        .join(if cfg!(target_os = "windows") {
            "decksmith-backend.exe"
        } else {
            "decksmith-backend"
        });
    if !executable.is_file() {
        return Err("Decksmith's bundled local service is missing. Reinstall Decksmith.".into());
    }
    let mut command = Command::new(executable);
    let demucs = resources
        .join("stem-runtime")
        .join(if cfg!(target_os = "windows") {
            "decksmith-demucs.exe"
        } else {
            "decksmith-demucs"
        });
    if demucs.is_file() {
        command.env("DECKSMITH_DEMUCS_EXECUTABLE", demucs);
    }
    let model_directory = resources.join("model-runtime");
    if model_directory.is_dir() {
        command.env("DECKSMITH_MODEL_DIR", model_directory);
    }
    command.current_dir(resources);
    Ok(command)
}

fn run_python(app: &AppHandle, arguments: &[&str]) -> Result<Value, String> {
    let database = database_path(app)?;
    let output = backend_command(app)?
        .arg("--database")
        .arg(database)
        .args(arguments)
        .output()
        .map_err(|error| format!("Could not start the library service: {error}"))?;

    if !output.status.success() {
        let error = String::from_utf8_lossy(&output.stderr).trim().to_string();
        return Err(if error.is_empty() {
            "Library service failed".into()
        } else {
            error
        });
    }

    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("Library service returned invalid data: {error}"))
}

fn allow_arrangement_audio(app: &AppHandle, payload: &Value) -> Result<(), String> {
    if let Some(clips) = payload.get("clips").and_then(Value::as_array) {
        for clip in clips {
            if let Some(path) = clip.get("path").and_then(Value::as_str) {
                app.asset_protocol_scope()
                    .allow_file(path)
                    .map_err(|error| {
                        format!("Could not allow arrangement audio access: {error}")
                    })?;
            }
        }
    }
    Ok(())
}

#[tauri::command]
fn load_assistant_matches(
    app: AppHandle,
    track_id: i64,
    limit: Option<i64>,
) -> Result<Value, String> {
    let id = track_id.to_string();
    let amount = limit.unwrap_or(12).to_string();
    run_python(&app, &["assistant-matches", &id, "--limit", &amount])
}

#[tauri::command]
fn load_assistant_drafts(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["assistant-drafts"])
}

#[tauri::command]
fn create_mashup_assistant_draft(
    app: AppHandle,
    anchor_track_id: i64,
    partner_track_id: i64,
    name: Option<String>,
) -> Result<Value, String> {
    let anchor = anchor_track_id.to_string();
    let partner = partner_track_id.to_string();
    let draft_name = name.unwrap_or_default();
    run_python(
        &app,
        &["assistant-mashup", &anchor, &partner, "--name", &draft_name],
    )
}

#[tauri::command]
fn create_setlist_assistant_draft(
    app: AppHandle,
    name: String,
    duration_minutes: i64,
    genre: String,
    energy_curve: String,
    must_play_track_ids: Vec<i64>,
    avoid_tags: Vec<String>,
) -> Result<Value, String> {
    let mut arguments = vec![
        "assistant-setlist".to_string(),
        name,
        duration_minutes.to_string(),
        "--genre".into(),
        genre,
        "--energy-curve".into(),
        energy_curve,
    ];
    for track_id in must_play_track_ids {
        arguments.extend(["--must-play".into(), track_id.to_string()]);
    }
    for tag in avoid_tags {
        arguments.extend(["--avoid-tag".into(), tag]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn create_arrangement_from_assistant_draft(app: AppHandle, draft_id: i64) -> Result<Value, String> {
    let id = draft_id.to_string();
    let payload = run_python(&app, &["assistant-draft-project", &id])?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn load_cache_status(app: AppHandle) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    let path = cache.to_string_lossy().to_string();
    run_python(&app, &["cache-status", &path])
}

#[tauri::command]
fn prune_app_cache(app: AppHandle) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    let path = cache.to_string_lossy().to_string();
    run_python(&app, &["cache-prune", &path])
}

fn show_package_path(path: &str) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let status = Command::new("open").arg(path).status();
    #[cfg(target_os = "windows")]
    let status = Command::new("explorer").arg(path).status();
    #[cfg(target_os = "linux")]
    let status = Command::new("xdg-open").arg(path).status();
    let status = status.map_err(|error| format!("Could not open the transfer folder: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err("The operating system could not open the transfer folder.".into())
    }
}

fn open_rekordbox_application() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    let status = Command::new("open").args(["-a", "rekordbox"]).status();
    #[cfg(target_os = "windows")]
    let status = Command::new("cmd")
        .args(["/C", "start", "", "rekordbox"])
        .status();
    #[cfg(target_os = "linux")]
    let status = Command::new("rekordbox").status();
    let status = status.map_err(|error| format!("Could not launch rekordbox: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err("rekordbox could not be launched. Confirm it is installed, then try again.".into())
    }
}

fn run_scan(app: &AppHandle, folder: &str) -> Result<Value, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    let cancel_file = app_data.join(format!("scan-cancel-{nonce}.flag"));
    let database = database_path(app)?;

    {
        let state = app.state::<ScanState>();
        let mut active = state
            .cancel_file
            .lock()
            .map_err(|_| "Scan state is unavailable")?;
        if active.is_some() {
            return Err("A library scan is already running.".into());
        }
        *active = Some(cancel_file.clone());
    }

    let result = (|| {
        let mut child = backend_command(app)?
            .arg("--database")
            .arg(database)
            .arg("scan")
            .arg(folder)
            .arg("--progress")
            .arg("--cancel-file")
            .arg(&cancel_file)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Could not start the library scanner: {error}"))?;

        let stdout = child
            .stdout
            .take()
            .ok_or("Library scanner did not provide progress output")?;
        let mut completed: Option<Value> = None;
        for line in BufReader::new(stdout).lines() {
            let line = line.map_err(|error| format!("Could not read scan progress: {error}"))?;
            let event: Value = serde_json::from_str(&line)
                .map_err(|error| format!("Library scanner returned invalid progress: {error}"))?;
            if event.get("event").and_then(Value::as_str) == Some("complete") {
                completed = event.get("data").cloned();
            }
            app.emit("scan-progress", &event)
                .map_err(|error| format!("Could not publish scan progress: {error}"))?;
        }

        let status = child
            .wait()
            .map_err(|error| format!("Could not finish library scan: {error}"))?;
        if !status.success() {
            let mut error = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                stderr
                    .read_to_string(&mut error)
                    .map_err(|read_error| read_error.to_string())?;
            }
            return Err(if error.trim().is_empty() {
                "Library scanner failed.".into()
            } else {
                error.trim().into()
            });
        }
        completed.ok_or_else(|| "Library scanner finished without a result.".into())
    })();

    if let Ok(mut active) = app.state::<ScanState>().cancel_file.lock() {
        *active = None;
    }
    let _ = std::fs::remove_file(cancel_file);
    result
}

fn run_analysis(app: &AppHandle, track_ids: &[i64], force: bool) -> Result<Value, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    let cancel_file = app_data.join(format!("analysis-cancel-{nonce}.flag"));
    let database = database_path(app)?;

    {
        let state = app.state::<AnalysisState>();
        let mut active = state
            .cancel_file
            .lock()
            .map_err(|_| "Analysis state is unavailable")?;
        if active.is_some() {
            return Err("Audio analysis is already running.".into());
        }
        *active = Some(cancel_file.clone());
    }

    let result = (|| {
        let mut command = backend_command(app)?;
        command
            .arg("--database")
            .arg(database)
            .arg("analyse")
            .arg("--progress")
            .arg("--cancel-file")
            .arg(&cancel_file);
        for track_id in track_ids {
            command.arg("--track-id").arg(track_id.to_string());
        }
        if force {
            command.arg("--force");
        }
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Could not start audio analysis: {error}"))?;

        let stdout = child
            .stdout
            .take()
            .ok_or("Audio analysis did not provide progress output")?;
        let mut completed: Option<Value> = None;
        for line in BufReader::new(stdout).lines() {
            let line =
                line.map_err(|error| format!("Could not read analysis progress: {error}"))?;
            let event: Value = serde_json::from_str(&line)
                .map_err(|error| format!("Audio analysis returned invalid progress: {error}"))?;
            if event.get("event").and_then(Value::as_str) == Some("complete") {
                completed = event.get("data").cloned();
            }
            app.emit("analysis-progress", &event)
                .map_err(|error| format!("Could not publish analysis progress: {error}"))?;
        }

        let status = child
            .wait()
            .map_err(|error| format!("Could not finish audio analysis: {error}"))?;
        if !status.success() {
            let mut error = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                stderr
                    .read_to_string(&mut error)
                    .map_err(|read_error| read_error.to_string())?;
            }
            return Err(if error.trim().is_empty() {
                "Audio analysis failed.".into()
            } else {
                error.trim().into()
            });
        }
        completed.ok_or_else(|| "Audio analysis finished without a result.".into())
    })();

    if let Ok(mut active) = app.state::<AnalysisState>().cancel_file.lock() {
        *active = None;
    }
    let _ = std::fs::remove_file(cancel_file);
    result
}

fn run_stem_separation(
    app: &AppHandle,
    track_id: i64,
    cache_directory: &Path,
    force: bool,
) -> Result<Value, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    let cancel_file = app_data.join(format!("stems-cancel-{nonce}.flag"));
    let database = database_path(app)?;

    {
        let state = app.state::<StemState>();
        let mut active = state
            .cancel_file
            .lock()
            .map_err(|_| "Stem state is unavailable")?;
        if active.is_some() {
            return Err("Stem separation is already running.".into());
        }
        *active = Some(cancel_file.clone());
    }

    let result = (|| {
        let mut command = backend_command(app)?;
        command
            .arg("--database")
            .arg(database)
            .arg("stems-separate")
            .arg(track_id.to_string())
            .arg(cache_directory)
            .arg("--progress")
            .arg("--cancel-file")
            .arg(&cancel_file);
        if force {
            command.arg("--force");
        }
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Could not start stem separation: {error}"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or("Stem separation did not provide progress output")?;
        let mut completed: Option<Value> = None;
        for line in BufReader::new(stdout).lines() {
            let line = line.map_err(|error| format!("Could not read stem progress: {error}"))?;
            let event: Value = serde_json::from_str(&line)
                .map_err(|error| format!("Stem separation returned invalid progress: {error}"))?;
            if event.get("event").and_then(Value::as_str) == Some("complete") {
                completed = event.get("data").cloned();
            }
            app.emit("stem-progress", &event)
                .map_err(|error| format!("Could not publish stem progress: {error}"))?;
        }
        let status = child
            .wait()
            .map_err(|error| format!("Could not finish stem separation: {error}"))?;
        if !status.success() {
            let mut error = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                stderr
                    .read_to_string(&mut error)
                    .map_err(|read_error| read_error.to_string())?;
            }
            return Err(if error.trim().is_empty() {
                "Stem separation failed.".into()
            } else {
                error.trim().into()
            });
        }
        completed.ok_or_else(|| "Stem separation finished without a result.".into())
    })();

    if let Ok(mut active) = app.state::<StemState>().cancel_file.lock() {
        *active = None;
    }
    let _ = std::fs::remove_file(cancel_file);
    result
}

fn run_clip_render(
    app: &AppHandle,
    clip_id: i64,
    cache_directory: &Path,
    force: bool,
) -> Result<Value, String> {
    let app_data = app
        .path()
        .app_data_dir()
        .map_err(|error| error.to_string())?;
    std::fs::create_dir_all(&app_data).map_err(|error| error.to_string())?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_nanos();
    let cancel_file = app_data.join(format!("render-cancel-{nonce}.flag"));
    let database = database_path(app)?;

    {
        let state = app.state::<RenderState>();
        let mut active = state
            .cancel_file
            .lock()
            .map_err(|_| "Render state is unavailable")?;
        if active.is_some() {
            return Err("A clip render is already running.".into());
        }
        *active = Some(cancel_file.clone());
    }

    let result = (|| {
        let mut command = backend_command(app)?;
        command
            .arg("--database")
            .arg(database)
            .arg("render-clip")
            .arg(clip_id.to_string())
            .arg(cache_directory)
            .arg("--progress")
            .arg("--cancel-file")
            .arg(&cancel_file);
        if force {
            command.arg("--force");
        }
        let mut child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| format!("Could not start clip rendering: {error}"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or("Clip rendering did not provide progress output")?;
        let mut completed: Option<Value> = None;
        for line in BufReader::new(stdout).lines() {
            let line = line.map_err(|error| format!("Could not read render progress: {error}"))?;
            let event: Value = serde_json::from_str(&line)
                .map_err(|error| format!("Clip rendering returned invalid progress: {error}"))?;
            if event.get("event").and_then(Value::as_str) == Some("complete") {
                completed = event.get("data").cloned();
            }
            app.emit("render-progress", &event)
                .map_err(|error| format!("Could not publish render progress: {error}"))?;
        }
        let status = child
            .wait()
            .map_err(|error| format!("Could not finish clip rendering: {error}"))?;
        if !status.success() {
            let mut error = String::new();
            if let Some(mut stderr) = child.stderr.take() {
                stderr
                    .read_to_string(&mut error)
                    .map_err(|read_error| read_error.to_string())?;
            }
            return Err(if error.trim().is_empty() {
                "Clip rendering failed.".into()
            } else {
                error.trim().into()
            });
        }
        completed.ok_or_else(|| "Clip rendering finished without a result.".into())
    })();

    if let Ok(mut active) = app.state::<RenderState>().cancel_file.lock() {
        *active = None;
    }
    let _ = std::fs::remove_file(cancel_file);
    result
}

#[tauri::command]
async fn scan_music_folder(app: AppHandle, folder: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_scan(&app, &folder))
        .await
        .map_err(|error| format!("Library scan task failed: {error}"))?
}

#[tauri::command]
fn cancel_music_scan(app: AppHandle) -> Result<bool, String> {
    let state = app.state::<ScanState>();
    let active = state
        .cancel_file
        .lock()
        .map_err(|_| "Scan state is unavailable")?;
    if let Some(path) = active.as_ref() {
        std::fs::write(path, b"cancel")
            .map_err(|error| format!("Could not cancel scan: {error}"))?;
        return Ok(true);
    }
    Ok(false)
}

#[tauri::command]
async fn analyse_library(
    app: AppHandle,
    track_ids: Option<Vec<i64>>,
    force: Option<bool>,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_analysis(
            &app,
            track_ids.as_deref().unwrap_or(&[]),
            force.unwrap_or(false),
        )
    })
    .await
    .map_err(|error| format!("Audio analysis task failed: {error}"))?
}

#[tauri::command]
fn cancel_audio_analysis(app: AppHandle) -> Result<bool, String> {
    let state = app.state::<AnalysisState>();
    let active = state
        .cancel_file
        .lock()
        .map_err(|_| "Analysis state is unavailable")?;
    if let Some(path) = active.as_ref() {
        std::fs::write(path, b"cancel")
            .map_err(|error| format!("Could not cancel analysis: {error}"))?;
        return Ok(true);
    }
    Ok(false)
}

#[tauri::command]
fn load_analysis_summary(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["analysis-summary"])
}

#[tauri::command]
fn load_stem_capability(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["stems-capability"])
}

#[tauri::command]
fn load_stem_status(app: AppHandle, track_ids: Vec<i64>) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("stems");
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&cache, true)
        .map_err(|error| format!("Could not allow stem cache access: {error}"))?;
    let mut arguments = vec!["stems-status".to_string()];
    for track_id in track_ids {
        arguments.extend(["--track-id".into(), track_id.to_string()]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
async fn separate_track_stems(
    app: AppHandle,
    track_id: i64,
    force: Option<bool>,
) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("stems");
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&cache, true)
        .map_err(|error| format!("Could not allow stem cache access: {error}"))?;
    tauri::async_runtime::spawn_blocking(move || {
        run_stem_separation(&app, track_id, &cache, force.unwrap_or(false))
    })
    .await
    .map_err(|error| format!("Stem separation task failed: {error}"))?
}

#[tauri::command]
fn cancel_stem_separation(app: AppHandle) -> Result<bool, String> {
    let state = app.state::<StemState>();
    let active = state
        .cancel_file
        .lock()
        .map_err(|_| "Stem state is unavailable")?;
    if let Some(path) = active.as_ref() {
        std::fs::write(path, b"cancel")
            .map_err(|error| format!("Could not cancel stem separation: {error}"))?;
        return Ok(true);
    }
    Ok(false)
}

#[tauri::command]
fn load_render_status(app: AppHandle, clip_ids: Vec<i64>) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("renders");
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&cache, true)
        .map_err(|error| format!("Could not allow render cache access: {error}"))?;
    let mut arguments = vec!["render-status".to_string()];
    for clip_id in clip_ids {
        arguments.extend(["--clip-id".into(), clip_id.to_string()]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
async fn render_arrangement_clip(
    app: AppHandle,
    clip_id: i64,
    force: Option<bool>,
) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("renders");
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&cache, true)
        .map_err(|error| format!("Could not allow render cache access: {error}"))?;
    tauri::async_runtime::spawn_blocking(move || {
        run_clip_render(&app, clip_id, &cache, force.unwrap_or(false))
    })
    .await
    .map_err(|error| format!("Clip render task failed: {error}"))?
}

#[tauri::command]
fn cancel_clip_render(app: AppHandle) -> Result<bool, String> {
    let state = app.state::<RenderState>();
    let active = state
        .cancel_file
        .lock()
        .map_err(|_| "Render state is unavailable")?;
    if let Some(path) = active.as_ref() {
        std::fs::write(path, b"cancel")
            .map_err(|error| format!("Could not cancel clip rendering: {error}"))?;
        return Ok(true);
    }
    Ok(false)
}

#[tauri::command]
fn load_library_tracks(app: AppHandle) -> Result<Value, String> {
    let roots = run_python(&app, &["roots"])?;
    if let Some(items) = roots.as_array() {
        for item in items {
            if let Some(path) = item.get("path").and_then(Value::as_str) {
                app.asset_protocol_scope()
                    .allow_directory(path, true)
                    .map_err(|error| format!("Could not allow audio preview access: {error}"))?;
            }
        }
    }
    run_python(&app, &["tracks"])
}

#[tauri::command]
fn load_music_folders(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["roots"])
}

#[tauri::command]
fn load_library_issues(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["issues"])
}

#[tauri::command]
async fn find_duplicate_tracks(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_python(&app, &["duplicates"]))
        .await
        .map_err(|error| format!("Duplicate analysis task failed: {error}"))?
}

#[tauri::command]
fn update_track_metadata(
    app: AppHandle,
    track_id: i64,
    rating: Option<u8>,
    tags: Option<Vec<String>>,
    color_tag: Option<String>,
    mood: Option<String>,
    comment: Option<String>,
) -> Result<Value, String> {
    let mut arguments = vec!["update-track".to_string(), track_id.to_string()];
    if let Some(value) = rating {
        arguments.extend(["--rating".into(), value.to_string()]);
    }
    if let Some(values) = tags {
        arguments.extend(["--tags".into(), values.join(",")]);
    }
    if let Some(value) = color_tag {
        arguments.extend(["--color-tag".into(), value]);
    }
    if let Some(value) = mood {
        arguments.extend(["--mood".into(), value]);
    }
    if let Some(value) = comment {
        arguments.extend(["--comment".into(), value]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn bulk_update_track_metadata(
    app: AppHandle,
    track_ids: Vec<i64>,
    rating: Option<u8>,
    tags: Option<Vec<String>>,
    color_tag: Option<String>,
    mood: Option<String>,
    tag_mode: Option<String>,
) -> Result<Value, String> {
    let mut arguments = vec!["bulk-update".to_string()];
    for track_id in track_ids {
        arguments.extend(["--track-id".into(), track_id.to_string()]);
    }
    if let Some(value) = rating {
        arguments.extend(["--rating".into(), value.to_string()]);
    }
    if let Some(values) = tags {
        arguments.extend(["--tags".into(), values.join(",")]);
    }
    if let Some(value) = color_tag {
        arguments.extend(["--color-tag".into(), value]);
    }
    if let Some(value) = mood {
        arguments.extend(["--mood".into(), value]);
    }
    arguments.extend([
        "--tag-mode".into(),
        tag_mode.unwrap_or_else(|| "add".into()),
    ]);
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn record_track_playback(app: AppHandle, track_id: i64) -> Result<Value, String> {
    let id = track_id.to_string();
    run_python(&app, &["record-playback", &id])
}

#[tauri::command]
async fn sync_serato_library(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_python(&app, &["serato-sync"]))
        .await
        .map_err(|error| format!("Serato import task failed: {error}"))?
}

#[tauri::command]
fn load_serato_crates(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["crates"])
}

#[tauri::command]
fn load_crate_tracks(app: AppHandle, crate_id: i64) -> Result<Value, String> {
    let id = crate_id.to_string();
    run_python(&app, &["crate-tracks", &id])
}

#[tauri::command]
async fn create_transfer_snapshot(app: AppHandle) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || run_python(&app, &["transfer-snapshot"]))
        .await
        .map_err(|error| format!("Transfer snapshot task failed: {error}"))?
}

#[tauri::command]
fn load_transfer_plan(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["transfer-plan"])
}

#[tauri::command]
async fn export_rekordbox_transfer(
    app: AppHandle,
    destination: String,
    crate_ids: Vec<i64>,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let mut arguments = vec!["transfer-export".to_string(), destination];
        for crate_id in crate_ids {
            arguments.extend(["--crate-id".to_string(), crate_id.to_string()]);
        }
        let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
        run_python(&app, &borrowed)
    })
    .await
    .map_err(|error| format!("Rekordbox export task failed: {error}"))?
}

#[tauri::command]
fn load_transfer_history(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["transfer-history"])
}

#[tauri::command]
async fn verify_transfer_package(app: AppHandle, destination: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        run_python(&app, &["transfer-verify", &destination])
    })
    .await
    .map_err(|error| format!("Transfer verification task failed: {error}"))?
}

#[tauri::command]
async fn reveal_transfer_package(app: AppHandle, destination: String) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let verification = run_python(&app, &["transfer-verify", &destination])?;
        show_package_path(&destination)?;
        Ok(verification)
    })
    .await
    .map_err(|error| format!("Transfer folder task failed: {error}"))?
}

#[tauri::command]
async fn launch_rekordbox() -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(open_rekordbox_application)
        .await
        .map_err(|error| format!("rekordbox launch task failed: {error}"))?
}

#[tauri::command]
async fn generate_track_waveform(app: AppHandle, track_id: i64) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let cache = app
            .path()
            .app_cache_dir()
            .map_err(|error| error.to_string())?
            .join("waveforms");
        std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
        app.asset_protocol_scope()
            .allow_directory(&cache, true)
            .map_err(|error| format!("Could not allow waveform cache access: {error}"))?;
        let id = track_id.to_string();
        let cache_path = cache.to_string_lossy().to_string();
        run_python(&app, &["waveform", &id, &cache_path])
    })
    .await
    .map_err(|error| format!("Waveform task failed: {error}"))?
}

#[tauri::command]
async fn generate_track_artwork(app: AppHandle, track_id: i64) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let cache = app
            .path()
            .app_cache_dir()
            .map_err(|error| error.to_string())?
            .join("artwork");
        std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
        app.asset_protocol_scope()
            .allow_directory(&cache, true)
            .map_err(|error| format!("Could not allow artwork cache access: {error}"))?;
        let id = track_id.to_string();
        let cache_path = cache.to_string_lossy().to_string();
        run_python(&app, &["artwork", &id, &cache_path])
    })
    .await
    .map_err(|error| format!("Artwork task failed: {error}"))?
}

#[tauri::command]
fn load_smart_playlists(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["smart-playlists"])
}

#[tauri::command]
fn create_smart_playlist(app: AppHandle, name: String, rules: Value) -> Result<Value, String> {
    let encoded = serde_json::to_string(&rules).map_err(|error| error.to_string())?;
    run_python(&app, &["smart-create", &name, &encoded])
}

#[tauri::command]
fn delete_smart_playlist(app: AppHandle, playlist_id: i64) -> Result<Value, String> {
    let id = playlist_id.to_string();
    run_python(&app, &["smart-delete", &id])
}

#[tauri::command]
fn load_smart_playlist_tracks(app: AppHandle, playlist_id: i64) -> Result<Value, String> {
    let id = playlist_id.to_string();
    run_python(&app, &["smart-tracks", &id])
}

#[tauri::command]
fn load_arrangement_projects(app: AppHandle) -> Result<Value, String> {
    run_python(&app, &["projects"])
}

#[tauri::command]
fn create_arrangement_project(app: AppHandle, name: String, tempo: f64) -> Result<Value, String> {
    let tempo_value = tempo.to_string();
    run_python(&app, &["project-create", &name, "--tempo", &tempo_value])
}

#[tauri::command]
fn load_arrangement_project(app: AppHandle, project_id: i64) -> Result<Value, String> {
    let id = project_id.to_string();
    let payload = run_python(&app, &["project-load", &id])?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn update_arrangement_project(
    app: AppHandle,
    project_id: i64,
    name: Option<String>,
    tempo: Option<f64>,
    snap_enabled: Option<bool>,
    snap_beats: Option<f64>,
    master_gain: Option<f64>,
    master_limiter: Option<bool>,
    musical_key: Option<String>,
    master_low_eq: Option<f64>,
    master_mid_eq: Option<f64>,
    master_high_eq: Option<f64>,
    master_width: Option<f64>,
    target_lufs: Option<f64>,
) -> Result<Value, String> {
    let mut arguments = vec!["project-update".to_string(), project_id.to_string()];
    if let Some(value) = name {
        arguments.extend(["--name".into(), value]);
    }
    if let Some(value) = tempo {
        arguments.extend(["--tempo".into(), value.to_string()]);
    }
    if let Some(value) = snap_enabled {
        arguments.extend([
            "--snap-enabled".into(),
            if value { "1".into() } else { "0".into() },
        ]);
    }
    if let Some(value) = snap_beats {
        arguments.extend(["--snap-beats".into(), value.to_string()]);
    }
    if let Some(value) = master_gain {
        arguments.extend(["--master-gain".into(), value.to_string()]);
    }
    if let Some(value) = master_limiter {
        arguments.extend([
            "--master-limiter".into(),
            if value { "1".into() } else { "0".into() },
        ]);
    }
    if let Some(value) = musical_key {
        arguments.extend(["--musical-key".into(), value]);
    }
    if let Some(value) = master_low_eq {
        arguments.extend(["--master-low-eq".into(), value.to_string()]);
    }
    if let Some(value) = master_mid_eq {
        arguments.extend(["--master-mid-eq".into(), value.to_string()]);
    }
    if let Some(value) = master_high_eq {
        arguments.extend(["--master-high-eq".into(), value.to_string()]);
    }
    if let Some(value) = master_width {
        arguments.extend(["--master-width".into(), value.to_string()]);
    }
    if let Some(value) = target_lufs {
        arguments.extend(["--target-lufs".into(), value.to_string()]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn add_track_to_arrangement(
    app: AppHandle,
    project_id: i64,
    track_id: i64,
    channel: i64,
    start_seconds: Option<f64>,
) -> Result<Value, String> {
    let mut arguments = vec![
        "project-add-track".to_string(),
        project_id.to_string(),
        track_id.to_string(),
        "--channel".into(),
        channel.to_string(),
    ];
    if let Some(value) = start_seconds {
        arguments.extend(["--start".into(), value.to_string()]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn add_stem_to_arrangement(
    app: AppHandle,
    source_clip_id: i64,
    stem_kind: String,
    channel: i64,
    start_seconds: Option<f64>,
) -> Result<Value, String> {
    let mut arguments = vec![
        "project-add-stem".to_string(),
        source_clip_id.to_string(),
        stem_kind,
        "--channel".into(),
        channel.to_string(),
    ];
    if let Some(value) = start_seconds {
        arguments.extend(["--start".into(), value.to_string()]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    let payload = run_python(&app, &borrowed)?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn freeze_arrangement_clip(app: AppHandle, clip_id: i64) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("consolidated");
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&cache, true)
        .map_err(|error| format!("Could not allow consolidated audio access: {error}"))?;
    let id = clip_id.to_string();
    let cache_path = cache.to_string_lossy().to_string();
    let payload = run_python(&app, &["project-clip-freeze", &id, &cache_path])?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn unfreeze_arrangement_clip(app: AppHandle, clip_id: i64) -> Result<Value, String> {
    let id = clip_id.to_string();
    let payload = run_python(&app, &["project-clip-unfreeze", &id])?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn bounce_arrangement_clip(app: AppHandle, clip_id: i64) -> Result<Value, String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("consolidated");
    std::fs::create_dir_all(&cache).map_err(|error| error.to_string())?;
    app.asset_protocol_scope()
        .allow_directory(&cache, true)
        .map_err(|error| format!("Could not allow consolidated audio access: {error}"))?;
    let id = clip_id.to_string();
    let cache_path = cache.to_string_lossy().to_string();
    let payload = run_python(&app, &["project-clip-bounce", &id, &cache_path])?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn reveal_consolidated_audio(app: AppHandle, path: String) -> Result<(), String> {
    let cache = app
        .path()
        .app_cache_dir()
        .map_err(|error| error.to_string())?
        .join("consolidated")
        .canonicalize()
        .map_err(|_| "Decksmith's consolidated-audio folder is unavailable.".to_string())?;
    let source = PathBuf::from(path)
        .canonicalize()
        .map_err(|_| "This consolidated audio file no longer exists.".to_string())?;
    if !source.is_file() || !source.starts_with(&cache) {
        return Err("Decksmith can only reveal audio created in its own cache.".into());
    }

    #[cfg(target_os = "macos")]
    let status = Command::new("open").arg("-R").arg(&source).status();
    #[cfg(target_os = "windows")]
    let status = Command::new("explorer")
        .arg(format!("/select,{}", source.display()))
        .status();
    #[cfg(target_os = "linux")]
    let status = Command::new("xdg-open")
        .arg(source.parent().unwrap_or(&cache))
        .status();
    let status = status.map_err(|error| format!("Could not reveal consolidated audio: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err("The operating system could not reveal this audio file.".into())
    }
}

#[tauri::command]
fn set_arrangement_clip_source(
    app: AppHandle,
    clip_id: i64,
    clip_kind: String,
) -> Result<Value, String> {
    let id = clip_id.to_string();
    let payload = run_python(&app, &["project-clip-source", &id, &clip_kind])?;
    allow_arrangement_audio(&app, &payload)?;
    Ok(payload)
}

#[tauri::command]
fn update_arrangement_stem_state(
    app: AppHandle,
    clip_id: i64,
    stem_kind: String,
    muted: Option<bool>,
    solo: Option<bool>,
) -> Result<Value, String> {
    let mut arguments = vec![
        "project-stem-state".to_string(),
        clip_id.to_string(),
        stem_kind,
    ];
    if let Some(value) = muted {
        arguments.extend([
            "--muted".into(),
            if value { "1".into() } else { "0".into() },
        ]);
    }
    if let Some(value) = solo {
        arguments.extend(["--solo".into(), if value { "1".into() } else { "0".into() }]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn update_arrangement_clip(app: AppHandle, clip_id: i64, changes: Value) -> Result<Value, String> {
    let id = clip_id.to_string();
    let encoded = serde_json::to_string(&changes).map_err(|error| error.to_string())?;
    run_python(&app, &["project-clip-update", &id, &encoded])
}

#[tauri::command]
fn resize_arrangement_clip(
    app: AppHandle,
    clip_id: i64,
    edge: String,
    boundary_seconds: f64,
) -> Result<Value, String> {
    let id = clip_id.to_string();
    let boundary = boundary_seconds.to_string();
    run_python(&app, &["project-clip-resize", &id, &edge, &boundary])
}

#[tauri::command]
fn split_arrangement_clip(
    app: AppHandle,
    clip_id: i64,
    offset_seconds: f64,
) -> Result<Value, String> {
    let id = clip_id.to_string();
    let offset = offset_seconds.to_string();
    run_python(&app, &["project-clip-split", &id, &offset])
}

#[tauri::command]
fn duplicate_arrangement_clip(app: AppHandle, clip_id: i64) -> Result<Value, String> {
    let id = clip_id.to_string();
    run_python(&app, &["project-clip-duplicate", &id])
}

#[tauri::command]
fn quantize_arrangement_clip(app: AppHandle, clip_id: i64) -> Result<Value, String> {
    let id = clip_id.to_string();
    run_python(&app, &["project-clip-quantize", &id])
}

#[tauri::command]
fn crossfade_arrangement_clips(
    app: AppHandle,
    clip_id: i64,
    target_clip_id: i64,
) -> Result<Value, String> {
    let id = clip_id.to_string();
    let target = target_clip_id.to_string();
    run_python(&app, &["project-clip-crossfade", &id, &target])
}

#[tauri::command]
fn group_arrangement_clips(app: AppHandle, clip_ids: Value) -> Result<Value, String> {
    let encoded = serde_json::to_string(&clip_ids).map_err(|error| error.to_string())?;
    run_python(&app, &["project-clip-group", &encoded])
}

#[tauri::command]
fn ungroup_arrangement_clips(
    app: AppHandle,
    project_id: i64,
    group_id: i64,
) -> Result<Value, String> {
    let project = project_id.to_string();
    let group = group_id.to_string();
    run_python(&app, &["project-clip-ungroup", &project, &group])
}

#[tauri::command]
fn batch_update_arrangement_clips(
    app: AppHandle,
    clip_ids: Value,
    changes: Value,
) -> Result<Value, String> {
    let ids = serde_json::to_string(&clip_ids).map_err(|error| error.to_string())?;
    let encoded = serde_json::to_string(&changes).map_err(|error| error.to_string())?;
    run_python(&app, &["project-clip-batch", &ids, &encoded])
}

#[tauri::command]
fn shift_arrangement_group_channels(
    app: AppHandle,
    project_id: i64,
    group_id: i64,
    delta: i64,
) -> Result<Value, String> {
    let project = project_id.to_string();
    let group = group_id.to_string();
    let shift = delta.to_string();
    run_python(&app, &["project-group-shift", &project, &group, &shift])
}

#[tauri::command]
fn delete_arrangement_clips(app: AppHandle, clip_ids: Value) -> Result<Value, String> {
    let ids = serde_json::to_string(&clip_ids).map_err(|error| error.to_string())?;
    run_python(&app, &["project-clip-delete", &ids])
}

#[tauri::command]
fn trim_arrangement_clips_to_selection(
    app: AppHandle,
    clip_ids: Value,
    start_seconds: f64,
    end_seconds: f64,
) -> Result<Value, String> {
    let ids = serde_json::to_string(&clip_ids).map_err(|error| error.to_string())?;
    let start = start_seconds.to_string();
    let end = end_seconds.to_string();
    run_python(&app, &["project-clip-trim-selection", &ids, &start, &end])
}

#[tauri::command]
fn create_arrangement_marker(
    app: AppHandle,
    project_id: i64,
    marker_kind: String,
    name: String,
    start_seconds: f64,
    end_seconds: Option<f64>,
    color: String,
) -> Result<Value, String> {
    let mut arguments = vec![
        "project-marker-create".to_string(),
        project_id.to_string(),
        "--kind".into(),
        marker_kind,
        "--name".into(),
        name,
        "--start".into(),
        start_seconds.to_string(),
        "--color".into(),
        color,
    ];
    if let Some(value) = end_seconds {
        arguments.extend(["--end".into(), value.to_string()]);
    }
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn update_arrangement_marker(
    app: AppHandle,
    marker_id: i64,
    changes: Value,
) -> Result<Value, String> {
    let id = marker_id.to_string();
    let encoded = serde_json::to_string(&changes).map_err(|error| error.to_string())?;
    run_python(&app, &["project-marker-update", &id, &encoded])
}

#[tauri::command]
fn delete_arrangement_marker(app: AppHandle, marker_id: i64) -> Result<Value, String> {
    let id = marker_id.to_string();
    run_python(&app, &["project-marker-delete", &id])
}

#[tauri::command]
fn update_arrangement_selection(
    app: AppHandle,
    project_id: i64,
    start_seconds: Option<f64>,
    end_seconds: Option<f64>,
    loop_enabled: bool,
) -> Result<Value, String> {
    let mut arguments = vec!["project-selection".to_string(), project_id.to_string()];
    match (start_seconds, end_seconds) {
        (Some(start), Some(end)) => arguments.extend([
            "--start".into(),
            start.to_string(),
            "--end".into(),
            end.to_string(),
        ]),
        _ => arguments.push("--clear".into()),
    }
    arguments.extend([
        "--loop-enabled".into(),
        if loop_enabled { "1".into() } else { "0".into() },
    ]);
    let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
    run_python(&app, &borrowed)
}

#[tauri::command]
fn undo_arrangement_project(app: AppHandle, project_id: i64) -> Result<Value, String> {
    let id = project_id.to_string();
    run_python(&app, &["project-undo", &id])
}

#[tauri::command]
fn redo_arrangement_project(app: AppHandle, project_id: i64) -> Result<Value, String> {
    let id = project_id.to_string();
    run_python(&app, &["project-redo", &id])
}

#[tauri::command]
async fn export_arrangement_audio(
    app: AppHandle,
    project_id: i64,
    destination: String,
    audio_format: String,
    loudness_targeted: bool,
) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let project = project_id.to_string();
        let mut arguments = vec![
            "project-export-audio".to_string(),
            project,
            destination,
            "--format".into(),
            audio_format,
        ];
        if loudness_targeted {
            arguments.push("--loudness-targeted".into());
        }
        let borrowed = arguments.iter().map(String::as_str).collect::<Vec<_>>();
        run_python(&app, &borrowed)
    })
    .await
    .map_err(|error| format!("Project audio export task failed: {error}"))?
}

#[tauri::command]
async fn audit_arrangement_project(app: AppHandle, project_id: i64) -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let project = project_id.to_string();
        run_python(&app, &["project-audit", &project])
    })
    .await
    .map_err(|error| format!("Smart Render task failed: {error}"))?
}

#[tauri::command]
fn load_latest_arrangement_audit(app: AppHandle, project_id: i64) -> Result<Value, String> {
    let project = project_id.to_string();
    run_python(&app, &["project-audit-latest", &project])
}

#[tauri::command]
fn load_arrangement_export_history(app: AppHandle, project_id: i64) -> Result<Value, String> {
    let project = project_id.to_string();
    run_python(&app, &["project-export-history", &project])
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(ScanState::default())
        .manage(AnalysisState::default())
        .manage(StemState::default())
        .manage(RenderState::default())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            load_assistant_matches,
            load_assistant_drafts,
            create_mashup_assistant_draft,
            create_setlist_assistant_draft,
            create_arrangement_from_assistant_draft,
            load_cache_status,
            prune_app_cache,
            scan_music_folder,
            cancel_music_scan,
            analyse_library,
            cancel_audio_analysis,
            load_analysis_summary,
            load_stem_capability,
            load_stem_status,
            separate_track_stems,
            cancel_stem_separation,
            load_render_status,
            render_arrangement_clip,
            cancel_clip_render,
            load_library_tracks,
            load_music_folders,
            load_library_issues,
            find_duplicate_tracks,
            update_track_metadata,
            bulk_update_track_metadata,
            record_track_playback,
            sync_serato_library,
            load_serato_crates,
            load_crate_tracks,
            create_transfer_snapshot,
            load_transfer_plan,
            export_rekordbox_transfer,
            load_transfer_history,
            verify_transfer_package,
            reveal_transfer_package,
            launch_rekordbox,
            generate_track_waveform,
            generate_track_artwork,
            load_smart_playlists,
            create_smart_playlist,
            delete_smart_playlist,
            load_smart_playlist_tracks,
            load_arrangement_projects,
            create_arrangement_project,
            load_arrangement_project,
            update_arrangement_project,
            add_track_to_arrangement,
            add_stem_to_arrangement,
            freeze_arrangement_clip,
            unfreeze_arrangement_clip,
            bounce_arrangement_clip,
            reveal_consolidated_audio,
            set_arrangement_clip_source,
            update_arrangement_stem_state,
            update_arrangement_clip,
            resize_arrangement_clip,
            split_arrangement_clip,
            duplicate_arrangement_clip,
            quantize_arrangement_clip,
            crossfade_arrangement_clips,
            group_arrangement_clips,
            ungroup_arrangement_clips,
            batch_update_arrangement_clips,
            shift_arrangement_group_channels,
            delete_arrangement_clips,
            trim_arrangement_clips_to_selection,
            create_arrangement_marker,
            update_arrangement_marker,
            delete_arrangement_marker,
            update_arrangement_selection,
            undo_arrangement_project,
            redo_arrangement_project,
            export_arrangement_audio,
            audit_arrangement_project,
            load_latest_arrangement_audit,
            load_arrangement_export_history
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
