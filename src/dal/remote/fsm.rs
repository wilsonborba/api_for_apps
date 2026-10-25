use crate::core::settings::Settings;
use anyhow::{Result, bail};
pub async fn upload(
    client: &reqwest::Client,
    s: &Settings,
    album: &str,
    name: String,
    mime: &str,
    data: Vec<u8>,
) -> Result<String> {
    let key = s.get("FSM_APP_KEY");
    if key.is_empty() {
        bail!("not configured")
    }
    let part = reqwest::multipart::Part::bytes(data)
        .file_name(name)
        .mime_str(mime)?;
    let form = reqwest::multipart::Form::new()
        .text("album", album.to_owned())
        .text("force", "false")
        .part("file", part);
    let response = client
        .post(format!(
            "{}/{}/media",
            s.get("FSM_MEDIA_ENDPOINT").trim_end_matches('/'),
            s.get("FSM_APP_NAME")
        ))
        .bearer_auth(key)
        .timeout(std::time::Duration::from_secs(90))
        .multipart(form)
        .send()
        .await?
        .error_for_status()?;
    let v: serde_json::Value = response.json().await?;
    let key = v["item"]["key"]
        .as_str()
        .filter(|v| !v.is_empty())
        .ok_or_else(|| anyhow::anyhow!("Invalid FSM upload response"))?;
    Ok(key.into())
}
