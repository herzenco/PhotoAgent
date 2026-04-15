use serde::Serialize;
use tauri::AppHandle;
use tauri_plugin_shell::ShellExt;

#[derive(Serialize)]
pub struct SidecarOutput {
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
}

#[tauri::command]
pub async fn run_photoagent(
    app: AppHandle,
    args: Vec<String>,
) -> Result<SidecarOutput, String> {
    let sidecar = app.shell()
        .sidecar("photoagent")
        .map_err(|e| format!("Failed to create sidecar: {}", e))?
        .args(&args);

    let output = sidecar
        .output()
        .await
        .map_err(|e| format!("Failed to run sidecar: {}", e))?;

    Ok(SidecarOutput {
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        exit_code: output.status.code().unwrap_or(-1),
    })
}
