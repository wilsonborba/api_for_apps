use crate::core::settings::Settings;
use anyhow::Result;
use serde_json::{Value, json};
/// Raw provider transport. Domain services own public error policy.
pub async fn request(
    client: &reqwest::Client,
    s: &Settings,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
    access: Option<&str>,
) -> Result<(reqwest::StatusCode, Value)> {
    let mut r = client
        .request(
            method,
            format!(
                "{}/auth/v1/{path}",
                s.get("SUPABASE_URL").trim_end_matches('/')
            ),
        )
        .header("apikey", s.get("SUPABASE_SECRET_KEY"));
    if let Some(token) = access {
        r = r.bearer_auth(token)
    }
    if let Some(body) = body {
        r = r.json(&body)
    }
    let r = r.send().await?;
    let status = r.status();
    Ok((status, r.json().await.unwrap_or(json!({}))))
}
