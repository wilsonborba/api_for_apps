use crate::domain::{State, auth};
use axum::{
    body::Body,
    http::{HeaderMap, Method, StatusCode},
    response::{IntoResponse, Response},
};
use serde_json::{Value, json};
/// Hop-by-hop headers and client credentials never cross the gateway: the admin key
/// and session cookie are verified here; backends receive the derived identity headers.
pub fn blocked(k: &str) -> bool {
    matches!(
        k,
        "authorization"
            | "cookie"
            | "connection"
            | "keep-alive"
            | "proxy-authenticate"
            | "proxy-authorization"
            | "te"
            | "trailers"
            | "transfer-encoding"
            | "upgrade"
            | "host"
            | "x-uuid"
            | "x-certifications-service-key"
            | "x-certifications-waitlist-registered"
    )
}
// Forwarding keeps protocol inputs explicit at this shared boundary.
#[allow(clippy::too_many_arguments)]
pub async fn forward(
    s: &State,
    app: &str,
    suffix: &str,
    query: Option<&str>,
    method: Method,
    h: &HeaderMap,
    body: axum::body::Bytes,
    extra: HeaderMap,
    ip: &str,
) -> Response {
    let Some(base) = s.settings.target(app) else {
        return crate::presentation::response(400, "Bad request", Value::Null);
    };
    let mut target = format!("{}{}", base.trim_end_matches('/'), suffix);
    if let Some(q) = query {
        target.push('?');
        target.push_str(q);
    }
    let mut headers = HeaderMap::new();
    for (k, v) in h {
        if !blocked(k.as_str()) {
            headers.append(k.clone(), v.clone());
        }
    }
    headers.extend(extra);
    headers.insert("x-forwarded-for", ip.parse().unwrap());
    headers.insert(
        "x-forwarded-proto",
        auth::header(h, "x-forwarded-proto")
            .parse()
            .unwrap_or_else(|_| "http".parse().unwrap()),
    );
    headers.insert(
        "x-forwarded-host",
        auth::header(h, "host")
            .parse()
            .unwrap_or_else(|_| "localhost".parse().unwrap()),
    );
    let r = s
        .client
        .request(method.clone(), target)
        .timeout(std::time::Duration::from_secs(3000))
        .headers(headers)
        .body(if method == Method::HEAD {
            axum::body::Bytes::new()
        } else {
            body
        })
        .send()
        .await;
    match r {
        Ok(up) => {
            let status = up.status();
            let mut headers = HeaderMap::new();
            for (k, v) in up.headers() {
                if !blocked(k.as_str()) {
                    headers.append(k.clone(), v.clone());
                }
            }
            let body = if method == Method::HEAD {
                Body::empty()
            } else {
                Body::from_stream(up.bytes_stream())
            };
            let mut out = Response::new(body);
            *out.status_mut() = status;
            *out.headers_mut() = headers;
            out
        }
        Err(e) => {
            tracing::error!(
                kind = if e.is_timeout() { "timeout" } else { "connect" },
                "Upstream proxy failed"
            );
            (
                StatusCode::BAD_REQUEST,
                axum::Json(json!({"message":"Bad request","data":null})),
            )
                .into_response()
        }
    }
}
