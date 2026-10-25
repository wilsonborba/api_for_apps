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
pub fn header<'a>(h: &'a HeaderMap, k: &str) -> &'a str {
    h.get(k).and_then(|v| v.to_str().ok()).unwrap_or("")
}
pub async fn session(s: &State, h: &HeaderMap) -> Result<Option<Value>> {
    if let Some(sid) = cookie(h, &s.settings.get("HTTP_ONLY_COOKIE_KEY_NAME")) {
        s.cache
            .get(
                &format!("{}:{sid}", s.settings.get("CACHE_AUTH_PREFIX")),
                false,
            )
            .await
    } else {
        Ok(None)
    }
}
pub async fn verify(s: &State, h: &HeaderMap, method: &str, admin: bool) -> Result<Option<Value>> {
    let key = header(h, &s.settings.get("API_ADMIN_KEY_NAME"));
    if !key.is_empty() && key == s.settings.get("API_KEY_SECRET") {
        return Ok(None);
    }
    let u = session(s, h)
        .await?
        .ok_or_else(|| anyhow!("Missing Authentications Parameters..."))?;
    if matches!(method, "POST" | "PUT" | "PATCH" | "DELETE") {
        let c = cookie(h, &s.settings.get("CSRF_COOKIE_KEY_NAME")).unwrap_or_default();
        if c.is_empty() || header(h, "x-csrf-token") != c || u["csrf_token"] != c {
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
pub async fn issue(s: &State, access: &str, app: &str) -> Result<String> {
    let p = provider(s, reqwest::Method::GET, "user", None, Some(access)).await?;
    let email = p["email"]
        .as_str()
        .ok_or_else(|| anyhow!("Supabase user payload is missing email or id"))?;
    let sub = p["id"]
        .as_str()
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
    let payload = json!({"jti":token(24),"app":app,"provider":"supabase","id":u["id"],"uuid_id":u["uuid_id"],"email":u["email"],"access_level":u["access_level"],"is_active":u["is_active"],"provider_user_id":sub,"exp":now()+s.settings.number("EXCHANGE_ARTIFACT_TTL_SECONDS",60) as i64});
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
    let sid = token(32);
    let u = json!({"session_id":sid,"provider_user_id":p["provider_user_id"],"access_level":p["access_level"],"user_id":p["id"],"user_uuid_id":p["uuid_id"],"email":p["email"],"csrf_token":token(24)});
    s.cache
        .set(
            &format!("{}:{sid}", s.settings.get("CACHE_AUTH_PREFIX")),
            u.clone(),
            s.settings.number("SESSION_TTL_SECONDS", 90000),
            false,
        )
        .await?;
    Ok(u)
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
