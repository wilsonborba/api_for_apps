//! Purpose-bound installed-app to browser continuation. Resource ownership stays
//! with the target application; this bridge transfers only trusted identity and
//! an opaque study reference, never study data or a client-supplied identity.
use super::auth;
use crate::domain::State;
use anyhow::{Result, bail};
use axum::http::HeaderMap;
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde_json::{Value, json};

pub const BROWSER_COOKIE: &str = "browser_handoff";
const PURPOSE: &str = "browser_study";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    Invalid,
    Authentication,
    Origin,
    Binding,
    AccountMismatch,
    Used,
    Expired,
    Cancelled,
    Disabled,
}
impl Failure {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "INVALID_BROWSER_HANDOFF",
            Self::Authentication => "BROWSER_HANDOFF_AUTH_REQUIRED",
            Self::Origin => "BROWSER_HANDOFF_ORIGIN_REFUSED",
            Self::Binding => "BROWSER_HANDOFF_BINDING_REFUSED",
            Self::AccountMismatch => "BROWSER_HANDOFF_ACCOUNT_MISMATCH",
            Self::Used => "BROWSER_HANDOFF_USED",
            Self::Expired => "BROWSER_HANDOFF_EXPIRED",
            Self::Cancelled => "BROWSER_HANDOFF_CANCELLED",
            Self::Disabled => "NATIVE_HANDOFF_DISABLED",
        }
    }
    pub fn status(self) -> u16 {
        match self {
            Self::Invalid => 400,
            Self::Authentication => 401,
            Self::Origin | Self::Binding | Self::Disabled => 403,
            Self::Expired => 410,
            _ => 409,
        }
    }
    pub fn message(self) -> &'static str {
        match self {
            Self::Invalid => "Invalid browser continuation.",
            Self::Authentication => "A valid installed-app session is required.",
            Self::Origin => "This browser origin is not permitted.",
            Self::Binding => "Preview this continuation in the same browser before continuing.",
            Self::AccountMismatch => "Confirm the account change before continuing.",
            Self::Used => "This continuation was already used. Go back to the app.",
            Self::Expired => "This continuation expired. Go back to the app.",
            Self::Cancelled => "This continuation was cancelled. Go back to the app.",
            Self::Disabled => "Installed-app login is disabled.",
        }
    }
}
impl std::fmt::Display for Failure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.message())
    }
}
impl std::error::Error for Failure {}

pub struct Preview {
    pub data: Value,
    pub browser_cookie: String,
    pub csrf_cookie: String,
    pub ttl: u64,
}
pub struct Redeemed {
    pub target_url: String,
    pub session: Option<Value>,
}

fn enabled(s: &State) -> Result<()> {
    if !auth::native_enabled(s) {
        bail!(Failure::Disabled)
    }
    Ok(())
}
fn fields(v: &Value, permitted: &[&str]) -> Result<()> {
    let Some(object) = v.as_object() else {
        bail!(Failure::Invalid)
    };
    if object.keys().any(|key| !permitted.contains(&key.as_str())) {
        bail!(Failure::Invalid)
    }
    Ok(())
}
fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| Failure::Invalid.into())
}
fn opaque(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}
fn id(value: &str) -> Result<()> {
    if !URL_SAFE_NO_PAD
        .decode(value)
        .is_ok_and(|bytes| bytes.len() == 32 && URL_SAFE_NO_PAD.encode(bytes) == value)
    {
        bail!(Failure::Invalid)
    }
    Ok(())
}
fn key(s: &State, value: &str) -> String {
    format!("{}:browser:{value}", s.settings.get("HANDOFF_PREFIX"))
}
fn auth_origin(s: &State) -> Result<url::Url> {
    let url = url::Url::parse(&s.settings.get(if s.settings.production() {
        "AUTH_APP_PROD_URL"
    } else {
        "AUTH_APP_LOCAL_URL"
    }))?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
    {
        bail!(Failure::Invalid)
    }
    Ok(url)
}
fn target_url(s: &State, app: &str, study: &str) -> Result<String> {
    if app != "certifications" || !s.settings.allowed_app(app) || !opaque(study) {
        bail!(Failure::Invalid)
    }
    let origins = s.settings.value("APP_EXCHANGE_ORIGINS");
    let origin = origins[app]
        .as_array()
        .and_then(|origins| {
            origins.iter().filter_map(Value::as_str).find(|origin| {
                origin.starts_with(if s.settings.production() {
                    "https://"
                } else {
                    "http://"
                })
            })
        })
        .ok_or(Failure::Invalid)?;
    let mut url = url::Url::parse(origin)?;
    if url.origin().ascii_serialization() != origin.trim_end_matches('/') {
        bail!(Failure::Invalid)
    }
    url.set_path(&format!("/studies/{study}"));
    Ok(url.to_string())
}
fn origin(s: &State, h: &HeaderMap, record: &Value) -> Result<String> {
    let origin = auth::header(h, "origin");
    let allowed = !origin.is_empty()
        && (origin == auth_origin(s)?.origin().ascii_serialization()
            || s.settings.origin_app(origin).as_deref() == Some(text(record, "target_app")?));
    if !allowed {
        bail!(Failure::Origin)
    }
    Ok(origin.into())
}
fn owner(u: &Value) -> Result<&str> {
    text(u, "user_uuid_id").map_err(|_| Failure::Authentication.into())
}
fn csrf(s: &State, h: &HeaderMap) -> Result<String> {
    let cookie = auth::cookie(h, &s.settings.get("CSRF_COOKIE_KEY_NAME")).unwrap_or_default();
    if cookie.is_empty() || !auth::same_secret(auth::header(h, "x-csrf-token"), &cookie) {
        bail!(Failure::Binding)
    }
    Ok(cookie)
}
async fn native_session(s: &State, h: &HeaderMap) -> Result<Value> {
    let u = auth::verify(s, h, "POST", false)
        .await
        .map_err(|_| Failure::Authentication)?
        .filter(|u| u["native"] == true)
        .ok_or(Failure::Authentication)?;
    owner(&u)?;
    Ok(u)
}
async fn source_session(s: &State, record: &Value) -> Result<Value> {
    let mut headers = HeaderMap::new();
    headers.insert(
        "cookie",
        format!(
            "{}={}",
            s.settings.get("HTTP_ONLY_COOKIE_KEY_NAME"),
            text(record, "source_session")?
        )
        .parse()?,
    );
    let u = auth::session(s, &headers)
        .await?
        .filter(|u| u["native"] == true)
        .ok_or(Failure::Authentication)?;
    if owner(&u)? != text(record, "user_uuid_id")? {
        bail!(Failure::Authentication)
    }
    Ok(u)
}
async fn live(s: &State, handoff: &str) -> Result<Value> {
    id(handoff)?;
    let record = s
        .cache
        .get(&key(s, handoff), false)
        .await?
        .ok_or(Failure::Expired)?;
    if record["purpose"] != PURPOSE {
        bail!(Failure::Invalid)
    }
    match record["status"].as_str() {
        Some("used") => bail!(Failure::Used),
        Some("cancelled") => bail!(Failure::Cancelled),
        Some("ready" | "bound") => {}
        _ => bail!(Failure::Invalid),
    }
    if auth::now() >= record["expires_at"].as_i64().unwrap_or(0) {
        bail!(Failure::Expired)
    }
    if target_url(s, text(&record, "target_app")?, text(&record, "study_id")?)?
        != text(&record, "target_url")?
    {
        bail!(Failure::Invalid)
    }
    Ok(record)
}
pub async fn create(s: &State, h: &HeaderMap, v: &Value) -> Result<Value> {
    enabled(s)?;
    fields(v, &["action", "target_app", "study_id"])?;
    let u = native_session(s, h).await?;
    let app = text(v, "target_app")?;
    let study = text(v, "study_id")?;
    let target = target_url(s, app, study)?;
    let at = auth::now();
    let expires = at + s.settings.number("HANDOFF_VALID_SECONDS", 300) as i64;
    let record = json!({"purpose":PURPOSE,"user_uuid_id":owner(&u)?,"source_session":u["session_id"],"target_app":app,"study_id":study,"target_url":target,"created_at":at,"expires_at":expires,"status":"ready"});
    let handoff = auth::token(32);
    if !s
        .cache
        .set(
            &key(s, &handoff),
            record,
            s.settings.number("HANDOFF_RECORD_TTL_SECONDS", 1800),
            true,
        )
        .await?
    {
        bail!(Failure::Invalid)
    }
    let mut launch = auth_origin(s)?;
    launch.set_path("/continue");
    launch.set_query(None);
    launch.set_fragment(None);
    launch.query_pairs_mut().append_pair("handoff_id", &handoff);
    Ok(json!({"launch_url":launch.to_string(),"expires_at":expires}))
}
pub async fn preview(s: &State, h: &HeaderMap, handoff: &str) -> Result<Preview> {
    enabled(s)?;
    loop {
        let old = live(s, handoff).await?;
        let origin = origin(s, h, &old)?;
        let source = source_session(s, &old).await?;
        let current = auth::session(s, h).await?;
        let browser = auth::cookie(h, BROWSER_COOKIE)
            .filter(|v| id(v).is_ok())
            .unwrap_or_else(|| auth::token(32));
        // A different cookie store cannot rebind an already inspected continuation.
        if old["status"] == "bound"
            && !auth::same_secret(old["browser_cookie"].as_str().unwrap_or(""), &browser)
        {
            bail!(Failure::Binding)
        }
        let csrf_cookie = auth::cookie(h, &s.settings.get("CSRF_COOKIE_KEY_NAME"))
            .filter(|v| !v.is_empty())
            .unwrap_or_else(|| auth::token(24));
        let state = auth::token(32);
        let browser_user = current.as_ref().map(owner).transpose()?;
        let mut next = old.clone();
        next["status"] = json!("bound");
        next["browser_cookie"] = json!(browser);
        next["browser_state"] = json!(state);
        next["csrf_token"] = json!(csrf_cookie);
        next["browser_user"] = json!(browser_user);
        next["browser_session"] = current
            .as_ref()
            .map(|u| u["session_id"].clone())
            .unwrap_or(Value::Null);
        next["origin"] = json!(origin);
        if s.cache
            .compare_and_swap(&key(s, handoff), &old, next, None, None)
            .await?
        {
            return Ok(Preview {
                data: json!({"account":{"email":source["email"]},"current_account":current.as_ref().map(|u| json!({"email":u["email"]})),"account_mismatch":browser_user.is_some_and(|user| user != source["user_uuid_id"]),"target_app":old["target_app"],"study_id":old["study_id"],"browser_state":state,"expires_at":old["expires_at"]}),
                browser_cookie: browser,
                csrf_cookie,
                ttl: (old["expires_at"].as_i64().unwrap_or(0) - auth::now()).max(1) as u64,
            });
        }
    }
}
async fn binding(s: &State, h: &HeaderMap, v: &Value, record: &Value) -> Result<Option<Value>> {
    let request_origin = origin(s, h, record)?;
    let browser = auth::cookie(h, BROWSER_COOKIE).unwrap_or_default();
    let state = text(v, "browser_state")?;
    id(state)?;
    if record["status"] != "bound"
        || record["origin"] != request_origin
        || !auth::same_secret(record["browser_cookie"].as_str().unwrap_or(""), &browser)
        || !auth::same_secret(record["browser_state"].as_str().unwrap_or(""), state)
        || !auth::same_secret(record["csrf_token"].as_str().unwrap_or(""), &csrf(s, h)?)
    {
        bail!(Failure::Binding)
    }
    let current = auth::session(s, h).await?;
    if current.as_ref().map(owner).transpose()? != record["browser_user"].as_str()
        || !auth::same_secret(
            current
                .as_ref()
                .and_then(|u| u["session_id"].as_str())
                .unwrap_or(""),
            record["browser_session"].as_str().unwrap_or(""),
        )
    {
        bail!(Failure::Binding)
    }
    if current.is_some() {
        auth::verify(s, h, "POST", false)
            .await
            .map_err(|_| Failure::Binding)?;
    }
    Ok(current)
}
pub async fn redeem(s: &State, h: &HeaderMap, v: &Value) -> Result<Redeemed> {
    enabled(s)?;
    fields(
        v,
        &[
            "action",
            "handoff_id",
            "browser_state",
            "confirm_account_switch",
        ],
    )?;
    if v.get("confirm_account_switch")
        .is_some_and(|value| !value.is_boolean())
    {
        bail!(Failure::Invalid)
    }
    let handoff = text(v, "handoff_id")?;
    loop {
        let old = live(s, handoff).await?;
        let current = binding(s, h, v, &old).await?;
        let source = source_session(s, &old).await?;
        if current
            .as_ref()
            .is_some_and(|u| u["user_uuid_id"] != old["user_uuid_id"])
            && v["confirm_account_switch"] != true
        {
            bail!(Failure::AccountMismatch)
        }
        let reuse = current
            .as_ref()
            .filter(|u| u["user_uuid_id"] == old["user_uuid_id"] && u["native"] != true);
        let u = reuse.cloned().unwrap_or_else(|| auth::new_session(&json!({"id":source["user_id"],"uuid_id":source["user_uuid_id"],"provider_user_id":source["provider_user_id"],"email":source["email"],"access_level":source["access_level"]}), false, auth::now()));
        let mut next = old.clone();
        next["status"] = json!("used");
        next["used_at"] = json!(auth::now());
        let session_key = auth::session_key(s, &u);
        let insert = if reuse.is_some() {
            None
        } else {
            Some((
                session_key.as_str(),
                u.clone(),
                s.settings.number("SESSION_TTL_SECONDS", 90000),
            ))
        };
        if s.cache
            .compare_and_swap(&key(s, handoff), &old, next, None, insert)
            .await?
        {
            return Ok(Redeemed {
                target_url: text(&old, "target_url")?.into(),
                session: if reuse.is_some() { None } else { Some(u) },
            });
        }
    }
}
pub async fn cancel(s: &State, h: &HeaderMap, v: &Value) -> Result<()> {
    enabled(s)?;
    fields(v, &["action", "handoff_id", "browser_state"])?;
    let handoff = text(v, "handoff_id")?;
    loop {
        let old = live(s, handoff).await?;
        if v.get("browser_state").is_some() {
            binding(s, h, v, &old).await?;
        } else {
            let u = native_session(s, h).await?;
            if owner(&u)? != text(&old, "user_uuid_id")?
                || !auth::same_secret(
                    u["session_id"].as_str().unwrap_or(""),
                    text(&old, "source_session")?,
                )
            {
                bail!(Failure::Authentication)
            }
        }
        let mut next = old.clone();
        next["status"] = json!("cancelled");
        if s.cache
            .compare_and_swap(&key(s, handoff), &old, next, None, None)
            .await?
        {
            return Ok(());
        }
    }
}
