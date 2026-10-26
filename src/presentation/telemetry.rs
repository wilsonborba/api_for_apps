use super::*;
use crate::{
    core::logs::Redactor,
    dal::local::telemetry::ReadQuery,
    domain::services::telemetry::{self as model, ClientError, EventBatch},
};
pub fn route(path: &str) -> bool {
    path.starts_with("/apps/api/v1/telemetry/")
}
pub async fn dispatch(
    s: &State,
    method: &Method,
    path: &str,
    query: Option<&str>,
    h: &HeaderMap,
    body: axum::body::Body,
    peer: std::net::IpAddr,
) -> Response {
    let suffix = path.strip_prefix("/apps/api/v1/telemetry/").unwrap_or("");
    if !["errors", "events", "sessions"].contains(&suffix) {
        return detail(404, "Unknown telemetry resource");
    }
    if method == Method::GET {
        return read(s, suffix, query, h).await;
    }
    if method != Method::POST || suffix == "sessions" {
        return detail(405, "Method Not Allowed");
    }
    if h.contains_key("origin") && !allowed_origin(auth::header(h, "origin")) {
        return detail(403, "Forbidden origin");
    }
    let ip = model::client_ip(h, peer);
    match s
        .cache
        .increment(&format!("ratelimit:tracking:{ip}"), 60)
        .await
    {
        Ok(count) if count <= model::REQUESTS_PER_MINUTE => {}
        Ok(_) => return detail(429, "Telemetry rate limit exceeded"),
        Err(_) => return detail(503, "Telemetry temporarily unavailable"),
    }
    let bytes = match to_bytes(body, model::MAX_BODY_BYTES).await {
        Ok(v) => v,
        Err(_) => return detail(413, "Telemetry body exceeds 65536 bytes"),
    };
    ingest(s, suffix, h, &bytes, &ip).await
}
pub async fn ingest(s: &State, kind: &str, h: &HeaderMap, bytes: &[u8], ip: &str) -> Response {
    let redactor = Redactor::new(&s.settings);
    let user = match model::user(s, h).await {
        Ok(user) => user,
        Err(_) => return detail(503, "Session lookup unavailable"),
    };
    if kind == "errors" {
        let mut value = match serde_json::from_slice::<ClientError>(bytes) {
            Ok(v) => v,
            Err(_) => return detail(422, "Invalid error payload"),
        };
        if !value.validate(&redactor) {
            return detail(422, "Invalid error payload");
        }
        if !s.db.log_app_active(&value.app_id).await.unwrap_or(false) {
            return detail(422, "Unknown or inactive app");
        }
        match s.db.insert_client_error(&value, user.as_deref()).await {
            Ok(()) => (StatusCode::ACCEPTED, axum::Json(json!({"accepted":1}))).into_response(),
            Err(_) => detail(503, "Error storage unavailable"),
        }
    } else {
        let mut value = match serde_json::from_slice::<EventBatch>(bytes) {
            Ok(v) => v,
            Err(_) => return detail(422, "Invalid event batch"),
        };
        if !value.validate(&redactor) {
            return detail(422, "Invalid event batch");
        }
        if !s.db.log_app_active(&value.app_id).await.unwrap_or(false) {
            return detail(422, "Unknown or inactive app");
        }
        let agent = auth::header(h, "user-agent")
            .chars()
            .take(500)
            .collect::<String>();
        match s
            .db
            .insert_event_batch(&value, user.as_deref(), ip, &agent)
            .await
        {
            Ok(count) => {
                (StatusCode::ACCEPTED, axum::Json(json!({"accepted":count}))).into_response()
            }
            Err(error) if error.to_string() == "session_identity_changed" => (
                StatusCode::CONFLICT,
                axum::Json(json!({"code":"session_identity_changed"})),
            )
                .into_response(),
            Err(_) => detail(503, "Usage storage unavailable"),
        }
    }
}
async fn read(s: &State, kind: &str, query: Option<&str>, h: &HeaderMap) -> Response {
    if auth::verify(s, h, "GET", true).await.is_err() {
        return detail(403, "Administrator access required");
    }
    let q: ReadQuery = match serde_urlencoded::from_str(query.unwrap_or("")) {
        Ok(q) => q,
        Err(_) => return detail(422, "Invalid telemetry query"),
    };
    if !(1..=200).contains(&q.limit.unwrap_or(100))
        || q.before_id.is_some_and(|v| v < 1)
        || (kind == "sessions" && q.before_id.is_some())
        || q.app_id.as_ref().is_some_and(|s| !model::app_valid(s))
        || q.session_id
            .as_ref()
            .is_some_and(|s| !model::session_valid(s))
        || matches!((q.from,q.to),(Some(from),Some(to)) if from>to)
    {
        return detail(422, "Invalid telemetry query");
    }
    let result = match kind {
        "errors" => s.db.client_errors(&q).await.map(|v| json!({"items":v})),
        "events" => s.db.usage_events(&q).await.map(|v| json!({"items":v})),
        _ => s.db.usage_sessions(&q).await.map(|v| json!({"items":v})),
    };
    match result {
        Ok(v) => axum::Json(v).into_response(),
        Err(_) => detail(503, "Telemetry storage unavailable"),
    }
}

/// Compatibility for deployed error reporters. All new writes use SQL, never CouchDB.
pub async fn legacy(
    s: &State,
    method: &Method,
    query: Option<&str>,
    h: &HeaderMap,
    body: axum::body::Body,
    peer: std::net::IpAddr,
) -> Response {
    if method == Method::GET {
        return read(s, "errors", query, h).await;
    }
    if method != Method::POST {
        return detail(405, "Method Not Allowed");
    }
    if h.contains_key("origin") && !allowed_origin(auth::header(h, "origin")) {
        return detail(403, "Forbidden origin");
    }
    let ip = model::client_ip(h, peer);
    match s
        .cache
        .increment(&format!("ratelimit:tracking:{ip}"), 60)
        .await
    {
        Ok(count) if count <= model::REQUESTS_PER_MINUTE => {}
        Ok(_) => return detail(429, "Telemetry rate limit exceeded"),
        Err(_) => return detail(503, "Telemetry temporarily unavailable"),
    }
    let bytes = match to_bytes(body, model::MAX_BODY_BYTES).await {
        Ok(v) => v,
        Err(_) => return detail(413, "Telemetry body too large"),
    };
    let value: Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(_) => return detail(422, "Invalid error payload"),
    };
    let old = |key: &str| value[key].as_str().unwrap_or("").to_owned();
    let error = ClientError {
        app_id: old("app_name").to_lowercase(),
        session_id: uuid::Uuid::new_v4().to_string(),
        route: old("route"),
        error_type: old("error_title"),
        message: old("error_message"),
        stack: old("stack_trace"),
        build_version: old("app_version"),
    };
    ingest(s, "errors", h, &serde_json::to_vec(&error).unwrap(), &ip).await
}
