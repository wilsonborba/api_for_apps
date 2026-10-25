pub mod auth_routes;
pub mod docs;
pub mod logs;
pub mod support_routes;
pub mod validation;
use crate::domain::{State, auth, proxy};
use axum::{
    Router,
    body::{Bytes, to_bytes},
    extract::{ConnectInfo, Request, State as Extract},
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Response},
};
use serde_json::{Value, json};
pub fn response(status: u16, message: &str, data: Value) -> Response {
    (
        StatusCode::from_u16(status).unwrap_or(StatusCode::INTERNAL_SERVER_ERROR),
        axum::Json(json!({"message":message,"data":data})),
    )
        .into_response()
}
pub fn detail(status: u16, message: &str) -> Response {
    (
        StatusCode::from_u16(status).unwrap(),
        axum::Json(json!({"detail":message})),
    )
        .into_response()
}
pub fn router(s: State) -> Router {
    Router::new().fallback(dispatch).with_state(s)
}
async fn dispatch(
    Extract(s): Extract<State>,
    ConnectInfo(addr): ConnectInfo<std::net::SocketAddr>,
    request: Request,
) -> Response {
    let (mut parts, body) = request.into_parts();
    let path = parts.uri.path().to_string();
    let method = parts.method.clone();
    let h = parts.headers.clone();
    let ip = addr.ip().to_string();
    let query = parts.uri.query().map(str::to_owned);
    let origin = auth::header(&h, "origin").to_owned();
    let cors = allowed_origin(&origin);
    let is_preflight = method == Method::OPTIONS
        && !origin.is_empty()
        && h.contains_key("access-control-request-method");
    if is_preflight {
        let mut r = if cors {
            StatusCode::OK.into_response()
        } else {
            (StatusCode::BAD_REQUEST, "Disallowed CORS origin").into_response()
        };
        add_cors(&mut r, &h, cors);
        return r;
    }
    if auth::header(&h, "upgrade").eq_ignore_ascii_case("websocket") {
        if let Some((app, suffix)) = path
            .strip_prefix("/apps/")
            .and_then(|p| p.split_once("/v1/"))
            && suffix == "logs/stream"
            && matches!(app, "cortex" | "certifications")
        {
            if let Err(e) = auth::verify(&s, &h, "GET", true).await {
                return detail(403, &e.to_string());
            }
            use axum::extract::FromRequestParts;
            return match axum::extract::ws::WebSocketUpgrade::from_request_parts(&mut parts, &())
                .await
            {
                Ok(upgrade) => {
                    logs::websocket(s, h, app.to_owned(), format!("/{suffix}"), upgrade).await
                }
                Err(_) => detail(400, "Invalid WebSocket upgrade"),
            };
        }
        return detail(404, "WebSocket route not found");
    }
    let out = if path == "/docs" && method == Method::GET {
        docs::page()
    } else if path == "/openapi.json" && method == Method::GET {
        docs::spec()
    } else if path == "/docs/favicon.svg" && method == Method::GET {
        docs::favicon()
    } else if path == "/apps/api/v1/logs/stream" && method == Method::GET {
        logs::stream(&s, &h).await
    } else {
        let bytes = match to_bytes(body, usize::MAX).await {
            Ok(v) => v,
            Err(_) => return detail(413, "Request body too large"),
        };
        handle(&s, &method, &path, query.as_deref(), &h, bytes, &ip).await
    };
    let mut out = out;
    add_cors(&mut out, &h, cors);
    tracing::info!(method=%method,path=%path,status=out.status().as_u16(),"Request completed");
    out
}
fn allowed_origin(origin: &str) -> bool {
    if matches!(
        origin,
        "https://auth.asodya.com"
            | "https://certifications.asodya.com"
            | "https://cortex.asodya.com"
            | "https://reports.asodya.com"
            | "https://wilson.asodya.com"
            | "https://wilsonborba.asodya.com"
            | "https://asodya.com"
            | "https://www.asodya.com"
    ) {
        return true;
    }
    regex::Regex::new(r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|172\.\d+\.\d+\.\d+|100\.\d+\.\d+\.\d+)(:\d+)?$").unwrap().is_match(origin)
}
fn add_cors(r: &mut Response, h: &HeaderMap, allowed: bool) {
    if allowed {
        let hs = r.headers_mut();
        if let Some(origin) = h.get("origin") {
            hs.insert("access-control-allow-origin", origin.clone());
            hs.insert("vary", "Origin".parse().unwrap());
        }
        hs.insert("access-control-allow-credentials", "true".parse().unwrap());
    }
    if h.contains_key("access-control-request-method") {
        let hs = r.headers_mut();
        hs.insert(
            "access-control-allow-methods",
            "GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD"
                .parse()
                .unwrap(),
        );
        hs.insert(
            "access-control-allow-headers",
            h.get("access-control-request-headers")
                .cloned()
                .unwrap_or_else(|| "Authorization,Content-Type,X-CSRF-Token".parse().unwrap()),
        );
        hs.insert("access-control-max-age", "600".parse().unwrap());
    }
}
async fn handle(
    s: &State,
    m: &Method,
    path: &str,
    q: Option<&str>,
    h: &HeaderMap,
    b: Bytes,
    ip: &str,
) -> Response {
    if matches!(
        path,
        "/user/info/v1" | "/user/info/v1/all/" | "/user/info/v1/fields/"
    ) {
        let target = if path.ends_with('/') {
            path.trim_end_matches('/').to_owned()
        } else {
            format!("{path}/")
        };
        let target = if let Some(q) = q {
            format!("{target}?{q}")
        } else {
            target
        };
        return (StatusCode::TEMPORARY_REDIRECT, [("location", target)]).into_response();
    }
    if validation::method_allowed(m.as_str(), path) == Some(false) {
        return detail(405, "Method Not Allowed");
    }
    if let Some(r) = validation::request(m.as_str(), path, h, &b) {
        return r;
    }
    if matches!(path, "/apps/api/v1/hello_apps" | "/user/v1/hello_user") && m == Method::GET {
        return docs::hello();
    }
    if path.starts_with("/user/") || path == "/apps/api/v1/exchange" {
        return auth_routes::handle(s, m, path, q, h, b, ip).await;
    }
    if let Some(rest) = path.strip_prefix("/apps/support/v1/") {
        return support_routes::handle(s, m, rest, q, h, b).await;
    }
    if matches!(
        path,
        "/apps/api/v1/client-error" | "/apps/api/v1/client-reports"
    ) {
        return telemetry(s, m, path, q, h, b, ip).await;
    }
    if path == "/apps/certifications/v1/waitlist" && m == Method::POST {
        return waitlist(s, h, b, ip).await;
    }
    if let Some(p) = path.strip_prefix("/apps/")
        && let Some((app, rest)) = p.split_once("/v1/")
    {
        let normalized_app = app.trim().to_lowercase();
        let app = normalized_app.as_str();
        if m == Method::OPTIONS {
            return StatusCode::NO_CONTENT.into_response();
        }
        if !matches!(
            *m,
            Method::GET
                | Method::POST
                | Method::PUT
                | Method::PATCH
                | Method::DELETE
                | Method::HEAD
        ) {
            return detail(405, "Method Not Allowed");
        }
        let suffix = format!("/{}", rest.trim_start_matches('/'));
        let decoded = percent_encoding::percent_decode_str(&suffix).decode_utf8_lossy();
        let admin = crate::core::settings::glob("/logs*", &decoded)
            || crate::core::settings::glob("*/logs*", &decoded)
            || s.settings
                .matches("ADMIN_PROTECTED_PROXY_ROUTES", app, m.as_str(), &decoded);
        let protected = admin
            || s.settings
                .matches("FORCE_AUTH_PROXY_ROUTES", app, m.as_str(), &decoded)
            || !s
                .settings
                .matches("PUBLIC_PROXY_ROUTES", app, m.as_str(), &decoded);
        let mut extra = HeaderMap::new();
        if protected {
            match auth::verify(s, h, m.as_str(), admin).await {
                Ok(u) => {
                    if !admin {
                        let u = match u {
                            Some(u) => Some(u),
                            None => auth::session(s, h).await.ok().flatten(),
                        };
                        if let Some(u) = u {
                            identity(&mut extra, &u)
                        } else {
                            return response(400, "Bad request", Value::Null);
                        }
                    } else if let Ok(Some(u)) = auth::session(s, h).await {
                        identity(&mut extra, &u)
                    }
                }
                Err(e) => return response(403, &e.to_string(), Value::Null),
            }
        }
        return proxy::forward(s, app, &suffix, q, m.clone(), h, b, extra, ip).await;
    }
    detail(404, "Not Found")
}
pub fn identity(h: &mut HeaderMap, u: &Value) {
    for (key, field) in [
        ("x-uuid", "user_uuid_id"),
        ("x-access-level", "access_level"),
        ("x-project-admin", "is_project_admin"),
    ] {
        if !u[field].is_null() {
            let v = u[field]
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| u[field].to_string());
            if let Ok(v) = v.parse() {
                h.insert(key, v);
            }
        }
    }
}
pub fn parse(b: &Bytes) -> Result<Value, Box<Response>> {
    serde_json::from_slice(b).map_err(|_| Box::new(detail(422, "Invalid JSON request body")))
}
pub fn text<'a>(b: &'a Value, k: &str) -> &'a str {
    b[k].as_str().unwrap_or("")
}
pub fn valid_string(b: &Value, k: &str, min: usize, max: usize, optional: bool) -> bool {
    if optional && (b.get(k).is_none() || b[k].is_null()) {
        return true;
    }
    b[k].as_str().is_some_and(|v| {
        let n = v.chars().count();
        n >= min && n <= max
    })
}
async fn telemetry(
    s: &State,
    m: &Method,
    path: &str,
    q: Option<&str>,
    h: &HeaderMap,
    b: Bytes,
    ip: &str,
) -> Response {
    if m == Method::GET && path.ends_with("client-error") {
        if let Err(e) = auth::verify(s, h, "GET", true).await {
            return detail(403, &e.to_string());
        }
        let query: std::collections::HashMap<_, _> =
            url::form_urlencoded::parse(q.unwrap_or("").as_bytes())
                .into_owned()
                .collect();
        for key in ["limit", "skip"] {
            if let Some(value) = query.get(key)
                && value.parse::<usize>().is_err()
            {
                return detail(422, "Invalid pagination parameter");
            }
        }
        let limit = query
            .get("limit")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(50);
        let skip = query
            .get("skip")
            .and_then(|v| v.parse::<usize>().ok())
            .unwrap_or(0);
        if !(1..=200).contains(&limit) {
            return detail(422, "Invalid limit");
        }
        let errors = s.telemetry.recent(limit, skip).await;
        return response(
            200,
            "Success",
            json!({"total":errors.len(),"errors":errors}),
        );
    }
    if m != Method::POST {
        return detail(405, "Method Not Allowed");
    }
    let mut v = match parse(&b) {
        Ok(v) => v,
        Err(r) => return *r,
    };
    for (k, min, max, opt) in [
        ("app_name", 2, 80, false),
        ("environment", 2, 32, false),
        ("error_title", 2, 200, false),
        ("error_message", 1, 4000, false),
        ("app_version", 0, 50, true),
        ("route", 0, 300, true),
        ("error_code", 0, 80, true),
        ("stack_trace", 0, 8000, true),
        ("request_id", 0, 100, true),
        ("user_agent", 0, 500, true),
        ("user_id", 0, 100, true),
        ("session_id", 0, 100, true),
        ("ip_address", 0, 64, true),
        ("client_timestamp", 0, 50, true),
        ("server_timestamp", 0, 50, true),
    ] {
        if !valid_string(&v, k, min, max, opt) {
            return detail(422, "Invalid telemetry payload");
        }
    }
    for k in ["details", "extra"] {
        if v.get(k).is_none() {
            v[k] = json!({})
        } else if !v[k].is_object() {
            return detail(422, "Invalid telemetry details");
        }
    }
    if let Some(obj) = v.as_object_mut() {
        obj.retain(|k, _| {
            [
                "app_name",
                "app_version",
                "environment",
                "route",
                "error_title",
                "error_message",
                "error_code",
                "stack_trace",
                "request_id",
                "user_id",
                "session_id",
                "ip_address",
                "user_agent",
                "client_timestamp",
                "server_timestamp",
                "details",
                "extra",
            ]
            .contains(&k.as_str())
        });
    }
    let origin = if h.contains_key("origin") {
        auth::header(h, "origin")
    } else {
        auth::header(h, "referer")
    };
    if !origin.is_empty()&&!origin.to_lowercase().contains(".asodya.com")&&!origin.to_lowercase().starts_with("https://asodya.com")&&!regex::Regex::new(r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|172\.\d+\.\d+\.\d+|100\.\d+\.\d+\.\d+)(:\d+)?").unwrap().is_match(origin){return response(403,"Forbidden origin.",Value::Null)}
    let real = if h.contains_key("cf-connecting-ip") {
        auth::header(h, "cf-connecting-ip")
    } else if h.contains_key("x-forwarded-for") {
        auth::header(h, "x-forwarded-for")
            .split(',')
            .next()
            .unwrap_or(ip)
    } else {
        ip
    };
    if s.cache
        .increment(&format!("ratelimit:telemetry:{real}"), 60)
        .await
        .unwrap_or(0)
        > 10
    {
        return response(429, "Rate limit exceeded. Try again later.", Value::Null);
    }
    let u = auth::session(s, h).await.ok().flatten();
    let id = uuid::Uuid::new_v4().to_string();
    v["error_id"] = json!(id);
    v["user_id"] = u
        .as_ref()
        .map(|u| {
            u.get("id")
                .or(u.get("user_id"))
                .cloned()
                .unwrap_or(Value::Null)
        })
        .unwrap_or(Value::Null);
    v["session_id"] = json!(auth::cookie(
        h,
        &s.settings.get("HTTP_ONLY_COOKIE_KEY_NAME")
    ));
    v["ip_address"] = json!(real);
    v["user_agent"] = h
        .get("user-agent")
        .and_then(|x| x.to_str().ok())
        .map(Value::from)
        .unwrap_or(Value::Null);
    v["server_timestamp"] = json!(crate::domain::support::timestamp());
    for k in [
        "app_version",
        "route",
        "error_code",
        "stack_trace",
        "request_id",
        "client_timestamp",
    ] {
        if v.get(k).is_none() {
            v[k] = Value::Null;
        }
    }
    let store = s.telemetry.clone();
    tokio::spawn(async move {
        if !store.put(&id, v).await {
            tracing::warn!("Client error persistence failed")
        }
    });
    response(202, "Telemetry accepted.", json!({"status":"queued"}))
}
async fn waitlist(s: &State, h: &HeaderMap, b: Bytes, ip: &str) -> Response {
    let v = match parse(&b) {
        Ok(v) => v,
        Err(r) => return *r,
    };
    let email = text(&v, "email").trim().to_lowercase();
    if email.len() < 3
        || email.len() > 320
        || !regex::Regex::new(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
            .unwrap()
            .is_match(&email)
        || v.get("plan").is_some_and(|x| x != "free")
    {
        return detail(422, "Invalid waitlist request");
    }
    if let Err(e) = auth::rate(s, h, ip, "waitlist", Some(&email), false).await {
        return response(
            if e.to_string().starts_with("Too many") {
                429
            } else {
                503
            },
            "Request could not be completed. Please try again later.",
            Value::Null,
        );
    }
    let mut page = 1;
    let registered = loop {
        match auth::provider(
            s,
            reqwest::Method::GET,
            &format!("admin/users?page={page}&per_page=1000"),
            None,
            None,
        )
        .await
        {
            Ok(v) => {
                let users = v["users"].as_array();
                if users.is_some_and(|us| {
                    us.iter()
                        .any(|u| text(u, "email").trim().to_lowercase() == email)
                }) {
                    break true;
                }
                if users.is_none_or(|us| us.len() < 1000) {
                    break false;
                }
                page += 1
            }
            Err(_) => {
                return response(
                    503,
                    "Waitlist is temporarily unavailable. Please try again later.",
                    Value::Null,
                );
            }
        }
    };
    let mut extra = HeaderMap::new();
    extra.insert(
        "x-certifications-service-key",
        s.settings
            .get("CERTIFICATIONS_SERVICE_KEY")
            .parse()
            .unwrap(),
    );
    extra.insert(
        "x-certifications-waitlist-registered",
        registered.to_string().parse().unwrap(),
    );
    proxy::forward(
        s,
        "certifications",
        "/waitlist",
        None,
        Method::POST,
        h,
        b,
        extra,
        ip,
    )
    .await
}
