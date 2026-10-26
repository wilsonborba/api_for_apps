//! Validated relational telemetry. Client identity and network identity are never trusted.
use crate::{
    core::logs::Redactor,
    domain::{State, auth},
};
use axum::http::HeaderMap;
use serde::{Deserialize, Serialize};

pub const MAX_BODY_BYTES: usize = 65_536;
pub const MAX_BATCH_EVENTS: usize = 50;
pub const REQUESTS_PER_MINUTE: u64 = 120;
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ClientError {
    pub app_id: String,
    pub session_id: String,
    pub route: String,
    pub error_type: String,
    pub message: String,
    #[serde(default)]
    pub stack: String,
    #[serde(default)]
    pub build_version: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UsageEvent {
    pub seq: i64,
    pub event_type: String,
    pub screen: String,
    pub route: String,
    pub path: String,
    pub element_id: String,
    pub element_label: String,
    pub element_path: String,
    pub value: Option<String>,
    #[serde(default)]
    pub sensitive: bool,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventBatch {
    pub app_id: String,
    pub session_id: String,
    #[serde(default)]
    pub locale: String,
    #[serde(default)]
    pub theme: String,
    #[serde(default)]
    pub viewport_width: i32,
    #[serde(default)]
    pub viewport_height: i32,
    pub events: Vec<UsageEvent>,
}
pub fn session_valid(id: &str) -> bool {
    uuid::Uuid::parse_str(id).is_ok() && id.len() <= 64
}
pub fn app_valid(id: &str) -> bool {
    !id.is_empty()
        && id.len() <= 64
        && id
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}
fn bounded(value: &str, max: usize) -> bool {
    value.len() <= max
}
pub fn safe_path(path: &str) -> String {
    path.split(['?', '#']).next().unwrap_or("/").to_owned()
}
pub fn sensitive_element(id: &str, label: &str) -> bool {
    let value = format!("{id} {label}").to_lowercase();
    [
        "password",
        "passwd",
        "token",
        "secret",
        "payment",
        "credit_card",
        "card_number",
        "cvv",
        "cvc",
    ]
    .iter()
    .any(|word| value.contains(word))
}
impl ClientError {
    pub fn validate(&mut self, redactor: &Redactor) -> bool {
        if !app_valid(&self.app_id)
            || !session_valid(&self.session_id)
            || self.error_type.is_empty()
            || self.message.is_empty()
            || !bounded(&self.route, 500)
            || !bounded(&self.error_type, 100)
            || !bounded(&self.message, 4000)
            || !bounded(&self.stack, 8000)
            || !bounded(&self.build_version, 80)
        {
            return false;
        }
        self.route = safe_path(&self.route);
        self.message = redactor.clean(&self.message);
        self.stack = redactor.clean(&self.stack);
        true
    }
}
impl EventBatch {
    pub fn validate(&mut self, redactor: &Redactor) -> bool {
        if !app_valid(&self.app_id)
            || !session_valid(&self.session_id)
            || self.events.is_empty()
            || self.events.len() > MAX_BATCH_EVENTS
            || !bounded(&self.locale, 35)
            || !bounded(&self.theme, 32)
            || !(0..=50000).contains(&self.viewport_width)
            || !(0..=50000).contains(&self.viewport_height)
        {
            return false;
        }
        let mut seqs = std::collections::HashSet::new();
        static ID: std::sync::LazyLock<regex::Regex> = std::sync::LazyLock::new(|| {
            regex::Regex::new(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$").unwrap()
        });
        for event in &mut self.events {
            if event.seq < 0
                || !seqs.insert(event.seq)
                || !["view", "click", "input", "submit", "scroll", "error_link"]
                    .contains(&event.event_type.as_str())
                || event.screen.is_empty()
                || !bounded(&event.screen, 160)
                || !bounded(&event.route, 500)
                || !bounded(&event.path, 500)
                || !ID.is_match(&event.element_id)
                || !bounded(&event.element_id, 200)
                || event.element_label.trim().is_empty()
                || !bounded(&event.element_label, 200)
                || event.element_path.trim().is_empty()
                || !bounded(&event.element_path, 600)
                || event.value.as_ref().is_some_and(|v| !bounded(v, 4000))
            {
                return false;
            }
            if event.sensitive || sensitive_element(&event.element_id, &event.element_label) {
                event.value = None;
            }
            event.path = safe_path(&event.path);
            event.route = safe_path(&event.route);
            event.value = event.value.as_ref().map(|v| redactor.clean(v));
        }
        true
    }
}
pub async fn user(s: &State, h: &HeaderMap) -> anyhow::Result<Option<String>> {
    Ok(auth::session(s, h).await?.and_then(|u| {
        u.get("user_uuid_id")
            .or_else(|| u.get("uuid_id"))
            .and_then(|v| v.as_str())
            .map(str::to_owned)
    }))
}
pub fn client_ip(headers: &HeaderMap, peer: std::net::IpAddr) -> String {
    // Cloudflare's trusted ingress is the local tunnel. Direct clients cannot set their IP.
    if peer.is_loopback()
        && let Ok(ip) = auth::header(headers, "cf-connecting-ip").parse::<std::net::IpAddr>()
    {
        return ip.to_string();
    }
    peer.to_string()
}
