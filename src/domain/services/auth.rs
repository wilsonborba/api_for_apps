use crate::domain::State;
use anyhow::{Result, anyhow, bail};
use axum::http::HeaderMap;
use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
pub fn token(n: usize) -> String {
    let bytes: Vec<u8> = (0..n).map(|_| rand::random::<u8>()).collect();
    URL_SAFE_NO_PAD.encode(bytes)
}
pub fn now() -> i64 {
    chrono::Utc::now().timestamp()
}
pub fn cookie(h: &HeaderMap, name: &str) -> Option<String> {
    h.get_all("cookie")
        .iter()
        .filter_map(|v| v.to_str().ok())
        .flat_map(|s| s.split(';'))
        .find_map(|s| {
            s.trim()
                .split_once('=')
                .filter(|(k, _)| *k == name)
                .map(|(_, v)| v.to_owned())
        })
}
/// Constant-time secret comparison: both sides are hashed to fixed-length digests and
/// every byte is folded, so timing does not reveal the matching prefix or the length.
pub fn same_secret(a: &str, b: &str) -> bool {
    let (x, y) = (Sha256::digest(a.as_bytes()), Sha256::digest(b.as_bytes()));
    x.iter()
        .zip(y.iter())
        .fold(0u8, |acc, (p, q)| acc | (p ^ q))
        == 0
}
pub fn header<'a>(h: &'a HeaderMap, k: &str) -> &'a str {
    h.get(k).and_then(|v| v.to_str().ok()).unwrap_or("")
}
const NATIVE_IDLE_SECONDS: u64 = 30 * 24 * 60 * 60;
const NATIVE_ABSOLUTE_SECONDS: i64 = 90 * 24 * 60 * 60;

pub async fn session(s: &State, h: &HeaderMap) -> Result<Option<Value>> {
    let Some(sid) = cookie(h, &s.settings.get("HTTP_ONLY_COOKIE_KEY_NAME")) else {
        return Ok(None);
    };
    let key = format!("{}:{sid}", s.settings.get("CACHE_AUTH_PREFIX"));
    loop {
        let Some(mut u) = s.cache.get(&key, false).await? else {
            return Ok(None);
        };
        if u["native"] != true {
            return Ok(Some(u));
        }
        if !native_enabled(s) {
            return Ok(None);
        }
        let at = now();
        let created = u["created_at"].as_i64().unwrap_or(0);
        let last = u["last_used_at"].as_i64().unwrap_or(0);
        if at >= created + NATIVE_ABSOLUTE_SECONDS || at >= last + NATIVE_IDLE_SECONDS as i64 {
            // Past the idle or absolute limit: the session ends and needs a new browser login.
            s.cache.delete(&key).await?;
            return Ok(None);
        }
        let previous = u.clone();
        u["last_used_at"] = json!(at);
        let ttl = NATIVE_IDLE_SECONDS.min((created + NATIVE_ABSOLUTE_SECONDS - at) as u64);
        if s.cache
            .compare_and_swap(&key, &previous, u.clone(), Some(ttl), None)
            .await?
        {
            return Ok(Some(u));
        }
    }
}
pub async fn verify(s: &State, h: &HeaderMap, method: &str, admin: bool) -> Result<Option<Value>> {
    let key = header(h, &s.settings.get("API_ADMIN_KEY_NAME"));
    let secret = s.settings.get("API_KEY_SECRET");
    if !key.is_empty() && !secret.is_empty() && same_secret(key, &secret) {
        return Ok(None);
    }
    let u = session(s, h)
        .await?
        .ok_or_else(|| anyhow!("Missing Authentications Parameters..."))?;
    if matches!(method, "POST" | "PUT" | "PATCH" | "DELETE") {
        let c = cookie(h, &s.settings.get("CSRF_COOKIE_KEY_NAME")).unwrap_or_default();
        if c.is_empty()
            || !same_secret(header(h, "x-csrf-token"), &c)
            || !same_secret(u["csrf_token"].as_str().unwrap_or(""), &c)
        {
            bail!("Missing Authentications Parameters...")
        }
    }
    if admin && u["access_level"].as_i64().unwrap_or(3) != 1 {
        bail!("Forbidden: Admin access required.")
    }
    Ok(Some(u))
}
pub async fn provider(
    s: &State,
    method: reqwest::Method,
    path: &str,
    body: Option<Value>,
    access: Option<&str>,
) -> Result<Value> {
    let (status, v) =
        crate::dal::remote::supabase::request(&s.client, &s.settings, method, path, body, access)
            .await?;
    if !status.is_success() {
        let detail = ["msg", "message", "error_description", "error"]
            .iter()
            .find_map(|k| v[k].as_str())
            .unwrap_or("Supabase authentication failed");
        let low = detail.to_lowercase();
        bail!(
            "{}",
            if low.contains("already registered") || low.contains("already been registered") {
                "This email is already registered. Check your inbox or sign in."
            } else if low.contains("not confirmed") || low.contains("not verified") {
                "Email not verified. Please confirm your email before signing in."
            } else {
                detail
            }
        )
    }
    Ok(v)
}
async fn authenticated_user(s: &State, access: &str, app: &str) -> Result<Value> {
    let p = provider(s, reqwest::Method::GET, "user", None, Some(access)).await?;
    let email = p["email"]
        .as_str()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow!("Supabase user payload is missing email or id"))?;
    let sub = p["id"]
        .as_str()
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow!("Supabase user payload is missing email or id"))?;
    let display = p["user_metadata"]["display_name"]
        .as_str()
        .or(p["user_metadata"]["full_name"].as_str())
        .unwrap_or("")
        .trim();
    let mut names = display.splitn(2, ' ');
    let first = names.next().filter(|v| !v.is_empty());
    let last = names.next();
    let ts = chrono::Utc::now().to_rfc3339();
    let u = if let Some(old) = s.db.find("defaultdb_user", "email", &json!(email)).await? {
        s.db.update("defaultdb_user",&old["id"],&json!({"last_login":ts,"supabase_user_id":sub,"first_name":old["first_name"].as_str().or(first),"last_name":old["last_name"].as_str().or(last)})).await?
    } else {
        use argon2::{Argon2, PasswordHasher, password_hash::SaltString};
        let salt =
            SaltString::encode_b64(&rand::random::<[u8; 16]>()).map_err(|e| anyhow!("{e}"))?;
        let hash = Argon2::new(
            argon2::Algorithm::Argon2id,
            argon2::Version::V0x13,
            argon2::Params::new(65536, 3, 4, None).expect("Argon2 parameters"),
        )
        .hash_password(token(32).as_bytes(), &salt)
        .map_err(|e| anyhow!("{e}"))?
        .to_string();
        s.db.insert("defaultdb_user",&json!({"uuid_id":uuid::Uuid::new_v4().simple().to_string(),"username":email.split('@').next(),"first_name":first,"last_name":last,"email":email,"password":hash,"access_level":3,"is_active":true,"last_login":ts,"date_joined":ts,"phone_number":null,"supabase_user_id":sub})).await?
    };
    if u["is_active"] != true {
        bail!("User account is inactive.")
    }
    if !s.settings.allowed_app(app) {
        bail!("Unsupported initiating application")
    }
    Ok(
        json!({"app":app,"provider":"supabase","id":u["id"],"uuid_id":u["uuid_id"],"email":u["email"],"access_level":u["access_level"],"is_active":u["is_active"],"provider_user_id":sub}),
    )
}
pub async fn issue(s: &State, access: &str, app: &str) -> Result<String> {
    let mut payload = authenticated_user(s, access, app).await?;
    payload["jti"] = json!(token(24));
    payload["exp"] = json!(now() + s.settings.number("EXCHANGE_ARTIFACT_TTL_SECONDS", 60) as i64);
    let f = fernet::Fernet::new(&s.settings.get("FERNET_KEY_SECRET"))
        .ok_or_else(|| anyhow!("Invalid Fernet configuration"))?;
    let ciphertext = f.encrypt(&serde_json::to_vec(&payload)?);
    if !s
        .cache
        .set(
            &format!(
                "{}:{}",
                s.settings.get("EXCHANGE_ARTIFACT_PREFIX"),
                payload["jti"].as_str().unwrap()
            ),
            json!({"app":app}),
            s.settings.number("EXCHANGE_ARTIFACT_TTL_SECONDS", 60),
            true,
        )
        .await?
    {
        bail!("Could not issue exchange artifact")
    }
    Ok(ciphertext)
}
pub async fn redeem(s: &State, t: &str, expected: &str) -> Result<Value> {
    let f = fernet::Fernet::new(&s.settings.get("FERNET_KEY_SECRET"))
        .ok_or_else(|| anyhow!("Invalid Fernet configuration"))?;
    let b = f
        .decrypt(t)
        .map_err(|_| anyhow!("Invalid exchange artifact"))?;
    let p: Value = serde_json::from_slice(&b)?;
    if p.get("exp").is_none() {
        bail!("Token does not have expiration field")
    }
    if now() > p["exp"].as_i64().unwrap_or(0) {
        bail!("Token has expired")
    }
    for field in [
        "jti",
        "app",
        "uuid_id",
        "email",
        "access_level",
        "is_active",
        "id",
        "provider_user_id",
    ] {
        if p.get(field).is_none() {
            bail!("Token is missing field...")
        }
        if !matches!(field, "jti" | "app") && p[field].is_null() {
            bail!("There is a field with None value")
        }
    }
    if p["provider"] != "supabase" {
        bail!("Unsupported identity provider")
    }
    if ![1, 2, 3].contains(&p["access_level"].as_i64().unwrap_or(0)) {
        bail!("Invalid access level")
    }
    if p["is_active"] != true {
        bail!("User is not active")
    }
    if p["app"] != expected {
        bail!("Exchange artifact is for a different application")
    }
    let key = format!(
        "{}:{}",
        s.settings.get("EXCHANGE_ARTIFACT_PREFIX"),
        p["jti"].as_str().unwrap_or("")
    );
    let v = s.cache.get(&key, true).await?;
    if v.as_ref().is_none_or(|v| v["app"] != expected) {
        bail!("Exchange artifact is invalid, expired, or already used")
    }
    let u = new_session(&p, false, now());
    let ttl = s.settings.number("SESSION_TTL_SECONDS", 90000);
    s.cache
        .set(&session_key(s, &u), u.clone(), ttl, false)
        .await?;
    Ok(u)
}
fn session_key(s: &State, u: &Value) -> String {
    format!(
        "{}:{}",
        s.settings.get("CACHE_AUTH_PREFIX"),
        u["session_id"].as_str().unwrap_or("")
    )
}
/// Shared session record for the web exchange and the installed-app finish step.
/// Native sessions also carry their creation and last-use times for the 30 and 90 day limits.
fn new_session(p: &Value, native: bool, at: i64) -> Value {
    let mut u = json!({"session_id":token(32),"provider_user_id":p["provider_user_id"],"access_level":p["access_level"],"user_id":p["id"],"user_uuid_id":p["uuid_id"],"email":p["email"],"csrf_token":token(24)});
    if native {
        u["native"] = json!(true);
        u["created_at"] = json!(at);
        u["last_used_at"] = json!(at);
    }
    u
}
pub async fn rate(
    s: &State,
    h: &HeaderMap,
    ip: &str,
    action: &str,
    email: Option<&str>,
    signup: bool,
) -> Result<()> {
    let real = header(h, "x-forwarded-for")
        .split(',')
        .next()
        .filter(|x| !x.is_empty())
        .unwrap_or(ip);
    for (n, w) in [(5, 60), (if signup { 30 } else { 20 }, 3600)] {
        if s.cache
            .increment(&format!("rl:ip:{action}:ip:{real}:{w}s"), w)
            .await?
            > n
        {
            bail!("Too many {action} attempts. Try again later.")
        }
    }
    if let Some(email) = email {
        let email = email.trim().to_lowercase();
        for (n, w) in [(3, 60), (10, 600)] {
            if s.cache
                .increment(&format!("rl:user:{action}:user:{email}:{w}s"), w)
                .await?
                > n
            {
                bail!("Too many {action} attempts for this user_email. Try again later.")
            }
        }
        if matches!(action, "login" | "signup" | "waitlist") {
            let ns = if action == "waitlist" {
                "backoff:waitlist"
            } else {
                "backoff:login"
            };
            let c = s
                .cache
                .increment(&format!("{ns}:user:{email}:ip:{real}"), 60)
                .await?;
            let ms = (150. * ((c + 1) as f64).log2()).min(1000.) as u64;
            tokio::time::sleep(std::time::Duration::from_millis(ms)).await;
        }
    }
    Ok(())
}
pub fn pkce(verifier: &str) -> String {
    URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes()))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HandoffFailure {
    Disabled,
    Invalid,
    NotFinished,
    Expired,
    Used,
    RefusedNetwork,
}
impl HandoffFailure {
    pub fn code(self) -> &'static str {
        match self {
            Self::Disabled => "NATIVE_HANDOFF_DISABLED",
            Self::Invalid => "INVALID_HANDOFF",
            Self::NotFinished => "HANDOFF_NOT_FINISHED",
            Self::Expired => "HANDOFF_EXPIRED",
            Self::Used => "HANDOFF_USED",
            Self::RefusedNetwork => "LOGIN_REFUSED_NETWORK",
        }
    }
    pub fn message(self) -> &'static str {
        match self {
            Self::Disabled => "Installed-app login is disabled.",
            Self::Invalid => "Invalid installed-app login fields.",
            Self::NotFinished => {
                "The login is not finished. Finish it in the browser, then click Finish."
            }
            Self::Expired => "This login expired. Start again.",
            Self::Used => "Start again.",
            Self::RefusedNetwork => "Login refused. The login came from a different location.",
        }
    }
}
impl std::fmt::Display for HandoffFailure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.message())
    }
}
impl std::error::Error for HandoffFailure {}

#[derive(Clone)]
pub struct HandoffRequest {
    pub id: String,
    pub challenge: String,
    pub platform: String,
}
pub fn native_enabled(s: &State) -> bool {
    s.settings.value("NATIVE_HANDOFF_ENABLED") == true
}
fn bytes32(value: &str) -> Result<Vec<u8>> {
    let bytes = URL_SAFE_NO_PAD
        .decode(value)
        .map_err(|_| HandoffFailure::Invalid)?;
    if bytes.len() != 32 || URL_SAFE_NO_PAD.encode(&bytes) != value {
        bail!(HandoffFailure::Invalid)
    }
    Ok(bytes)
}
/// Handoff mode starts only when handoff_id is present, so current web payloads keep their behavior.
pub fn handoff_request(s: &State, app: &str, v: &Value) -> Result<Option<HandoffRequest>> {
    if v.get("handoff_id").is_none_or(Value::is_null) {
        return Ok(None);
    }
    if !native_enabled(s) {
        bail!(HandoffFailure::Disabled)
    }
    let field = |key: &str| v[key].as_str().ok_or(HandoffFailure::Invalid);
    let id = field("handoff_id")?;
    let challenge = field("challenge")?;
    let platform = field("platform")?;
    bytes32(id)?;
    bytes32(challenge)?;
    if !s.settings.allowed_app(app)
        || !s.settings.value("NATIVE_APP_PLATFORMS")[app]
            .as_array()
            .is_some_and(|platforms| platforms.iter().any(|v| v == platform))
    {
        bail!(HandoffFailure::Invalid)
    }
    Ok(Some(HandoffRequest {
        id: id.into(),
        challenge: challenge.into(),
        platform: platform.into(),
    }))
}
/// Client address for the network match. Only the local Cloudflare tunnel may set it through
/// cf-connecting-ip (same rule as telemetry); a direct client cannot choose its own address.
pub fn client_ip(h: &HeaderMap, peer: &str) -> Result<std::net::IpAddr> {
    let peer: std::net::IpAddr = peer.parse().map_err(|_| HandoffFailure::Invalid)?;
    let ip: std::net::IpAddr = super::telemetry::client_ip(h, peer)
        .parse()
        .map_err(|_| HandoffFailure::Invalid)?;
    Ok(match ip {
        std::net::IpAddr::V6(ip) => ip
            .to_ipv4_mapped()
            .map(std::net::IpAddr::V4)
            .unwrap_or(ip.into()),
        ip => ip,
    })
}
pub fn network(ip: std::net::IpAddr) -> String {
    match ip {
        std::net::IpAddr::V4(ip) => {
            let b = ip.octets();
            format!("{}.{}.{}.0/24", b[0], b[1], b[2])
        }
        std::net::IpAddr::V6(ip) => {
            let b = ip.segments();
            format!("{:x}:{:x}:{:x}:{:x}::/64", b[0], b[1], b[2], b[3])
        }
    }
}
fn handoff_key(s: &State, id: &str) -> String {
    format!("{}:{id}", s.settings.get("HANDOFF_PREFIX"))
}

pub async fn complete_login(
    s: &State,
    access: &str,
    app: &str,
    handoff: Option<&HandoffRequest>,
    h: &HeaderMap,
    ip: &str,
) -> Result<Value> {
    match handoff {
        None => Ok(json!(issue(s, access, app).await?)),
        Some(handoff) => {
            if !native_enabled(s) {
                bail!(HandoffFailure::Disabled)
            }
            let ip = client_ip(h, ip)?;
            let user = authenticated_user(s, access, app).await?;
            let expires = store_handoff(s, app, handoff, user, ip).await?;
            Ok(json!({"expires_at":expires}))
        }
    }
}
pub async fn store_handoff(
    s: &State,
    app: &str,
    handoff: &HandoffRequest,
    user: Value,
    ip: std::net::IpAddr,
) -> Result<i64> {
    if !native_enabled(s) {
        bail!(HandoffFailure::Disabled)
    }
    let at = now();
    let expires = at + s.settings.number("HANDOFF_VALID_SECONDS", 300) as i64;
    let record = json!({"app":app,"platform":handoff.platform,"challenge":handoff.challenge,"user":user,"ip":ip.to_string(),"network":network(ip),"created_at":at,"expires_at":expires,"status":"done","used_at":null,"session_id":null,"csrf_token":null});
    if !s
        .cache
        .set(
            &handoff_key(s, &handoff.id),
            record,
            s.settings.number("HANDOFF_RECORD_TTL_SECONDS", 1800),
            true,
        )
        .await?
    {
        bail!(HandoffFailure::Used)
    }
    Ok(expires)
}
fn native_result(u: &Value, at: i64) -> Value {
    let remaining =
        (u["created_at"].as_i64().unwrap_or(0) + NATIVE_ABSOLUTE_SECONDS - at).max(0) as u64;
    json!({"session_id":u["session_id"],"csrf_token":u["csrf_token"],"expires_in":NATIVE_IDLE_SECONDS.min(remaining)})
}
pub async fn finish_handoff(
    s: &State,
    v: &Value,
    h: &HeaderMap,
    fallback_ip: &str,
) -> Result<Value> {
    if !native_enabled(s) {
        bail!(HandoffFailure::Disabled)
    }
    let id = v["handoff_id"].as_str().ok_or(HandoffFailure::Invalid)?;
    let secret = v["secret"].as_str().ok_or(HandoffFailure::Invalid)?;
    bytes32(id)?;
    let challenge = URL_SAFE_NO_PAD.encode(Sha256::digest(bytes32(secret)?));
    let app = v["app"].as_str().ok_or(HandoffFailure::Invalid)?;
    if !s.settings.allowed_app(app) {
        bail!(HandoffFailure::Invalid)
    }
    let net = network(client_ip(h, fallback_ip)?);
    let key = handoff_key(s, id);
    loop {
        let Some(old) = s.cache.get(&key, false).await? else {
            bail!(HandoffFailure::NotFinished)
        };
        let at = now();
        // The secret and app prove the caller is the app that started the login; only then
        // does a network mismatch get its own answer (section 4.3) instead of plain used.
        let owner =
            same_secret(&challenge, old["challenge"].as_str().unwrap_or("")) && old["app"] == app;
        let valid = owner && old["network"] == net;
        match old["status"].as_str() {
            Some("used") => {
                if valid
                    && old["used_at"].as_i64().is_some_and(|used| {
                        at < used + s.settings.number("HANDOFF_RETRY_SECONDS", 120) as i64
                    })
                {
                    let sid = old["session_id"].as_str().filter(|sid| !sid.is_empty());
                    let live = match sid {
                        Some(sid) => {
                            s.cache
                                .get(
                                    &format!("{}:{sid}", s.settings.get("CACHE_AUTH_PREFIX")),
                                    false,
                                )
                                .await?
                        }
                        None => None,
                    };
                    if let Some(u) = live
                        && u["native"] == true
                        && at < u["created_at"].as_i64().unwrap_or(0) + NATIVE_ABSOLUTE_SECONDS
                        && at < u["last_used_at"].as_i64().unwrap_or(0) + NATIVE_IDLE_SECONDS as i64
                    {
                        // Return the same live session; never write or revive it from the saved result.
                        return Ok(native_result(&u, at));
                    }
                }
                bail!(HandoffFailure::Used)
            }
            Some("expired") => bail!(HandoffFailure::Expired),
            Some("done") => {}
            _ => bail!(HandoffFailure::Used),
        }
        let mut next = old.clone();
        if at >= old["expires_at"].as_i64().unwrap_or(0) {
            next["status"] = json!("expired");
            if s.cache
                .compare_and_swap(&key, &old, next, None, None)
                .await?
            {
                bail!(HandoffFailure::Expired)
            }
            continue;
        }
        next["status"] = json!("used");
        next["used_at"] = json!(at);
        if !valid {
            if s.cache
                .compare_and_swap(&key, &old, next, None, None)
                .await?
            {
                // Only this first refused finish tells the app why; the record now answers used.
                bail!(if owner {
                    HandoffFailure::RefusedNetwork
                } else {
                    HandoffFailure::Used
                })
            }
            continue;
        }
        let u = new_session(&old["user"], true, at);
        next["session_id"] = u["session_id"].clone();
        next["csrf_token"] = u["csrf_token"].clone();
        if s.cache
            .compare_and_swap(
                &key,
                &old,
                next,
                None,
                Some((&session_key(s, &u), u.clone(), NATIVE_IDLE_SECONDS)),
            )
            .await?
        {
            return Ok(native_result(&u, at));
        }
    }
}
