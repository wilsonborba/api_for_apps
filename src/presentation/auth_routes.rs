use super::*;
use crate::domain::auth;
pub async fn handle(
    s: &State,
    m: &Method,
    path: &str,
    _q: Option<&str>,
    h: &HeaderMap,
    b: Bytes,
    ip: &str,
) -> Response {
    if !matches!(
        path,
        "/user/info/v1/"
            | "/user/info/v1/all"
            | "/user/info/v1/fields"
            | "/user/sync/v1/log-out"
            | "/user/sync/v1/log-in"
            | "/user/sync/v1/sign-up"
            | "/user/sync/v1/password-recovery"
            | "/user/sync/v1/email-confirmation-resend"
            | "/user/sync/v1/reset-password"
            | "/user/sync/v1/oauth/start"
            | "/user/sync/v1/oauth/callback"
            | "/apps/api/v1/exchange"
    ) {
        return detail(404, "Not Found");
    }
    if path.starts_with("/user/info/v1") {
        return user_info(s, m, path, h, b).await;
    }
    if path == "/user/sync/v1/log-out" && m == Method::POST {
        if let Err(e) = auth::verify(s, h, "POST", false).await {
            return detail(403, &e.to_string());
        }
        if let Some(sid) = auth::cookie(h, &s.settings.get("HTTP_ONLY_COOKIE_KEY_NAME")) {
            let _ = s
                .cache
                .delete(&format!("{}:{sid}", s.settings.get("CACHE_AUTH_PREFIX")))
                .await;
        }
        let mut r = response(200, "Logged out successfully.", Value::Null);
        cookies(s, h, &mut r, None);
        return r;
    }
    let v = match parse(&b) {
        Ok(v) => v,
        Err(r) => {
            return if path == "/apps/api/v1/exchange" {
                response(400, "Bad request", Value::Null)
            } else {
                *r
            };
        }
    };
    if path == "/apps/api/v1/exchange" && m == Method::POST {
        let token = v["auth_exchange_token"]
            .as_str()
            .filter(|t| !t.is_empty())
            .or(v["token"].as_str())
            .unwrap_or("");
        if token.is_empty() {
            return response(400, "Authentication is required", Value::Null);
        }
        let Some(app) = s.settings.origin_app(auth::header(h, "origin")) else {
            return response(
                400,
                "Exchange origin is not registered for an application",
                Value::Null,
            );
        };
        if v["app"]
            .as_str()
            .is_some_and(|x| !x.is_empty() && x.trim().to_lowercase() != app)
        {
            return response(
                400,
                "Exchange application does not match its registered origin",
                Value::Null,
            );
        }
        return match auth::redeem(s, token, &app).await {
            Ok(u) => {
                let mut r = response(200, "Success", Value::Null);
                cookies(s, h, &mut r, Some(&u));
                r
            }
            Err(e) if e.to_string() == "Invalid exchange artifact" => {
                response(503, "Internal Server Error", Value::Null)
            }
            Err(e) => response(400, &e.to_string(), Value::Null),
        };
    }
    let Some(action) = path.strip_prefix("/user/sync/v1/") else {
        return detail(404, "Not Found");
    };
    if action == "oauth/start" && m == Method::POST {
        return oauth_start(s, &v).await;
    }
    if action == "oauth/callback" && m == Method::POST {
        return oauth_callback(s, &v).await;
    }
    let login = action == "log-in" && m == Method::PATCH;
    let signup = action == "sign-up" && m == Method::POST;
    if login || signup {
        let action = if signup { "signup" } else { "login" };
        let access = text(&v, "access_token");
        let email = text(&v, "email");
        if access.is_empty() && email.is_empty() {
            return detail(400, "email is required");
        }
        if let Err(e) = auth::rate(
            s,
            h,
            ip,
            action,
            if access.is_empty() { Some(email) } else { None },
            signup,
        )
        .await
        {
            return detail(
                if e.to_string().starts_with("Too many") {
                    429
                } else {
                    503
                },
                &e.to_string(),
            );
        }
        let app = v["app"]
            .as_str()
            .unwrap_or("certifications")
            .trim()
            .to_lowercase();
        let res: anyhow::Result<Option<String>> = async {
            let access = if !access.is_empty() {
                access.to_owned()
            } else {
                if !regex::Regex::new(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
                    .unwrap()
                    .is_match(email)
                {
                    anyhow::bail!("Invalid email format.")
                }
                let mut payload = json!({"email":email,"password":text(&v,"password")});
                if signup && !text(&v, "display_name").is_empty() {
                    payload["data"] = json!({"display_name":v["display_name"]})
                }
                let path = if signup {
                    format!(
                        "signup?redirect_to={}",
                        url::form_urlencoded::byte_serialize(s.settings.auth_url(false).as_bytes())
                            .collect::<String>()
                    )
                } else {
                    "token?grant_type=password".into()
                };
                let r =
                    auth::provider(s, reqwest::Method::POST, &path, Some(payload), None).await?;
                match r["access_token"].as_str() {
                    Some(t) => t.to_owned(),
                    None if signup => return Ok(None),
                    _ => anyhow::bail!("Supabase did not return an authenticated session"),
                }
            };
            Ok(Some(auth::issue(s, &access, &app).await?))
        }
        .await;
        return match res {
            Ok(Some(t)) => response(
                if signup { 201 } else { 200 },
                if signup {
                    "User signed up successfully."
                } else {
                    "User logged in successfully."
                },
                json!(t),
            ),
            Ok(None) => response(
                201,
                "User signed up successfully. Email confirmation is required before sign in can continue.",
                Value::Null,
            ),
            Err(e) => response(if signup { 400 } else { 401 }, &e.to_string(), Value::Null),
        };
    }
    if m != Method::POST {
        return detail(405, "Method Not Allowed");
    }
    let (field, provider_path, success, failure, method) = match action {
        "password-recovery" => (
            "email",
            "recover",
            "Password recovery email sent successfully.",
            "Failed to send password recovery email.",
            reqwest::Method::POST,
        ),
        "email-confirmation-resend" => (
            "email",
            "resend",
            "Confirmation email sent successfully.",
            "Failed to resend confirmation email.",
            reqwest::Method::POST,
        ),
        "reset-password" => (
            "new_password",
            "user",
            "Password updated successfully.",
            "Failed to update password.",
            reqwest::Method::PUT,
        ),
        _ => return detail(404, "Not Found"),
    };
    if !v[field].is_string() || (action == "reset-password" && !v["access_token"].is_string()) {
        return detail(422, "Missing required field");
    }
    if action != "reset-password"
        && let Err(e) = auth::rate(
            s,
            h,
            ip,
            if action == "password-recovery" {
                "password_recovery"
            } else {
                "email_confirmation_resend"
            },
            Some(text(&v, "email")),
            false,
        )
        .await
    {
        return detail(429, &e.to_string());
    }
    let payload = if action == "reset-password" {
        json!({"password":v["new_password"]})
    } else if action == "email-confirmation-resend" {
        json!({"type":"signup","email":v["email"]})
    } else {
        json!({"email":v["email"]})
    };
    let provider_path = if action == "reset-password" {
        provider_path.to_owned()
    } else {
        format!(
            "{provider_path}?redirect_to={}",
            url::form_urlencoded::byte_serialize(
                s.settings
                    .auth_url(action == "password-recovery")
                    .as_bytes()
            )
            .collect::<String>()
        )
    };
    match auth::provider(
        s,
        method,
        &provider_path,
        Some(payload),
        if action == "reset-password" {
            Some(text(&v, "access_token"))
        } else {
            None
        },
    )
    .await
    {
        Ok(_) => response(200, success, Value::Null),
        Err(_) => response(400, failure, Value::Null),
    }
}
fn cookies(s: &State, h: &HeaderMap, r: &mut Response, u: Option<&Value>) {
    let host = auth::header(h, "x-forwarded-host");
    let host = if host.is_empty() {
        auth::header(h, "host").split(':').next().unwrap_or("")
    } else {
        host
    };
    let domain = if host
        .to_lowercase()
        .ends_with(&s.settings.get("ASODYA_MAIN_DOMAIN"))
    {
        format!("; Domain={}", s.settings.get("COOKIE_DOMAIN_PROD"))
    } else {
        String::new()
    };
    let secure = if auth::header(h, "x-forwarded-proto").eq_ignore_ascii_case("https") {
        "; Secure"
    } else {
        ""
    };
    for (key, field, ttl, http_only) in [
        (
            "HTTP_ONLY_COOKIE_KEY_NAME",
            "session_id",
            s.settings.number("SESSION_TTL_SECONDS", 90000),
            "; HttpOnly",
        ),
        (
            "CSRF_COOKIE_KEY_NAME",
            "csrf_token",
            s.settings.number("CSRF_TTL_SECONDS", 86400),
            "",
        ),
    ] {
        let value = u.map(|v| text(v, field)).unwrap_or("");
        let ttl = if u.is_some() { ttl } else { 0 };
        let cookie = format!(
            "{}={value}; Path=/; Max-Age={ttl}; SameSite=lax{domain}{secure}{http_only}",
            s.settings.get(key)
        );
        r.headers_mut()
            .append("set-cookie", cookie.parse().unwrap());
    }
}
async fn oauth_start(s: &State, v: &Value) -> Response {
    if !v["provider"].is_string() || !v["app"].is_string() {
        return detail(422, "Missing required field");
    }
    let p = text(v, "provider").trim().to_lowercase();
    let p = if p == "microsoft" { "azure" } else { &p };
    if !["google", "github", "azure"].contains(&p) {
        return response(400, "Unsupported OAuth provider", Value::Null);
    }
    let app = text(v, "app").trim().to_lowercase();
    if !s.settings.allowed_app(&app) {
        return response(400, "Unsupported initiating application", Value::Null);
    }
    let state = auth::token(32);
    let verifier = auth::token(64);
    let val = json!({"provider":p,"app":app,"intent":v["intent"].as_str().unwrap_or("login"),"code_verifier":verifier,"created_at":auth::now()});
    if s.cache
        .set(
            &format!("{}:{state}", s.settings.get("OAUTH_STATE_PREFIX")),
            val,
            600,
            false,
        )
        .await
        .is_err()
    {
        return response(503, "Internal Server Error", Value::Null);
    }
    let mut u = url::Url::parse(&format!(
        "{}/auth/v1/authorize",
        s.settings.get("SUPABASE_URL")
    ))
    .unwrap();
    {
        let mut q = u.query_pairs_mut();
        q.append_pair("provider", p)
            .append_pair("redirect_to", &s.settings.auth_url(false))
            .append_pair("state", &state)
            .append_pair("flow_type", "pkce")
            .append_pair("code_challenge", &auth::pkce(&verifier))
            .append_pair("code_challenge_method", "s256");
        if p == "azure" {
            q.append_pair("scopes", "email");
        }
    }
    response(
        200,
        "OAuth authorization URL created successfully.",
        json!({"authorization_url":u.as_str()}),
    )
}
async fn oauth_callback(s: &State, v: &Value) -> Response {
    if !text(v, "error").is_empty() {
        return response(
            400,
            v["error_description"].as_str().unwrap_or(text(v, "error")),
            Value::Null,
        );
    }
    if text(v, "code").is_empty() || text(v, "state").is_empty() {
        return response(400, "OAuth callback is missing code or state.", Value::Null);
    }
    let key = format!(
        "{}:{}",
        s.settings.get("OAUTH_STATE_PREFIX"),
        text(v, "state")
    );
    let Ok(Some(old)) = s.cache.get(&key, false).await else {
        return response(400, "OAuth state is missing or expired.", Value::Null);
    };
    let app = text(&old, "app").trim().to_lowercase();
    if !s.settings.allowed_app(&app) {
        let _ = s.cache.delete(&key).await;
        return response(
            400,
            "OAuth state has no valid initiating application.",
            Value::Null,
        );
    }
    let res: anyhow::Result<String> = async {
        let r = auth::provider(
            s,
            reqwest::Method::POST,
            "token?grant_type=pkce",
            Some(json!({"auth_code":v["code"],"code_verifier":old["code_verifier"]})),
            None,
        )
        .await?;
        let access = r["session"]["access_token"]
            .as_str()
            .ok_or_else(|| anyhow::anyhow!("Missing provider session"))?;
        let t = auth::issue(s, access, &app).await?;
        s.cache.delete(&key).await?;
        Ok(t)
    }
    .await;
    match res {
        Ok(t) => response(200, "OAuth callback completed successfully.", json!(t)),
        Err(_) => response(400, "Failed to complete the OAuth callback.", Value::Null),
    }
}
async fn user_info(s: &State, m: &Method, path: &str, h: &HeaderMap, b: Bytes) -> Response {
    let u = match auth::verify(s, h, m.as_str(), false).await {
        Ok(u) => u,
        Err(e) => return detail(403, &e.to_string()),
    };
    let out:anyhow::Result<(Value,&str)>=async{if path.ends_with("/all")&&m==Method::GET{let mut users=s.db.all("defaultdb_user").await?;for u in &mut users{u.as_object_mut().unwrap().remove("password");}return Ok((json!(users),"All user information retrieved successfully.") )}
if path.ends_with("/fields")&&m==Method::GET{return Ok((s.db.fields().await?,"User information fields retrieved successfully."))}let u=u.ok_or_else(||anyhow::anyhow!("Missing user session"))?;if m==Method::PATCH{let v:Value=serde_json::from_slice(&b)?;s.db.update("defaultdb_user",&u["user_id"],&json!({"first_name":v["first_name"],"last_name":v["last_name"],"phone_number":v["phone_number"]})).await?;Ok((Value::Null,"User information updated successfully."))}else{let mut row=s.db.find("defaultdb_user","id",&u["user_id"]).await?.unwrap_or(Value::Null);if let Some(row)=row.as_object_mut(){row.remove("password");}Ok((row,"User information retrieved successfully."))}}.await;
    match out {
        Ok((v, msg)) => response(200, msg, v),
        Err(_) => response(
            if m == Method::PATCH { 500 } else { 400 },
            if m == Method::PATCH {
                "Failed to update user information."
            } else {
                "Failed to retrieve user information."
            },
            Value::Null,
        ),
    }
}
