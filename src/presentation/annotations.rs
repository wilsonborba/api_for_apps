//! Explicit Annotations v2 boundary. Trusted LAN services remain authentication-free.
use crate::domain::{State, auth, proxy};
use axum::{
    body::{Body, to_bytes},
    http::{HeaderMap, Method},
    response::Response,
};
use futures_util::StreamExt;
use std::{
    collections::HashMap,
    net::IpAddr,
    sync::{Mutex, OnceLock},
};

const FEEDBACK_MAX_CONCURRENT_PER_ACCOUNT: usize = 4;
const FEEDBACK_MAX_CONCURRENT_PER_IP: usize = 8;
const FEEDBACK_RATE_PER_ACCOUNT_MINUTE: u64 = 30;
const FEEDBACK_RATE_PER_IP_MINUTE: u64 = 60;

static FEEDBACK_INFLIGHT: OnceLock<Mutex<HashMap<String, usize>>> = OnceLock::new();

struct InflightGuard {
    keys: Vec<String>,
}

impl Drop for InflightGuard {
    fn drop(&mut self) {
        if let Some(map) = FEEDBACK_INFLIGHT.get()
            && let Ok(mut guard) = map.lock()
        {
            for key in &self.keys {
                if let Some(count) = guard.get_mut(key) {
                    if *count <= 1 {
                        guard.remove(key);
                    } else {
                        *count -= 1;
                    }
                }
            }
        }
    }
}

fn acquire_feedback_slot(account: &str, ip: &str) -> Option<InflightGuard> {
    let map = FEEDBACK_INFLIGHT.get_or_init(|| Mutex::new(HashMap::new()));
    let mut guard = map.lock().unwrap_or_else(|e| e.into_inner());
    let acct_key = format!("acct:{account}");
    let ip_key = format!("ip:{ip}");
    let acct_count = guard.get(&acct_key).copied().unwrap_or(0);
    let ip_count = guard.get(&ip_key).copied().unwrap_or(0);
    if acct_count >= FEEDBACK_MAX_CONCURRENT_PER_ACCOUNT
        || ip_count >= FEEDBACK_MAX_CONCURRENT_PER_IP
    {
        return None;
    }
    guard.insert(acct_key.clone(), acct_count + 1);
    guard.insert(ip_key.clone(), ip_count + 1);
    Some(InflightGuard {
        keys: vec![acct_key, ip_key],
    })
}

pub(super) fn public(method: &Method, path: &str) -> bool {
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    matches!(
        (method.as_str(), parts.as_slice()),
        ("GET", ["health" | "ready" | "catalog" | "notes"])
            | ("GET", ["notes" | "media" | "authors" | "projects", _])
            | ("GET", ["authors", _, "projects"])
            | ("GET", ["links", "preview"])
            | ("POST", ["waitlist"])
            | ("GET" | "PUT" | "PATCH", ["instant", _])
            | ("POST", ["instant", _, "items" | "files"])
            | ("PUT" | "PATCH" | "DELETE", ["instant", _, "items", _])
            | ("GET", ["instant", _, "files", _])
            | ("PUT", ["instant", _, "files", _, "content"])
    )
}

pub(super) fn session(path: &str) -> bool {
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    matches!(parts.as_slice(), ["models"] | ["models", _] | ["me", _, ..])
}

pub(super) fn administrator(path: &str) -> bool {
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    if matches!(parts.as_slice(), ["admin", "images" | "posts", ..]) {
        return false;
    }
    path == "/logs/stream" || path.starts_with("/admin/")
}

pub(super) fn client_ip(peer: IpAddr, headers: &HeaderMap) -> IpAddr {
    auth::request_ip(headers, peer)
}

#[allow(clippy::too_many_arguments)]
pub async fn forward(
    s: &State,
    method: &Method,
    path: &str,
    query: Option<&str>,
    incoming: &HeaderMap,
    body: Body,
    peer: IpAddr,
) -> Response {
    if !path.starts_with('/')
        || path.contains('%')
        || path.contains("//")
        || path.split('/').any(|p| p == "." || p == "..")
    {
        return super::detail(404, "Not Found");
    }
    let is_admin = administrator(path);
    let is_session = !is_admin && session(path);
    let is_public = !is_admin && !is_session && public(method, path);
    if !is_admin && !is_session && !is_public {
        return super::detail(404, "Not Found");
    }

    let mut extra = HeaderMap::new();
    let mut account_id = String::new();
    if is_admin {
        match auth::verify(s, incoming, method.as_str(), true).await {
            Ok(Some(user)) => {
                if super::identity(s, &mut extra, &user).await.is_err() {
                    return super::detail(503, "Account information unavailable");
                }
            }
            Ok(None) => {
                extra.insert("x-access-level", "1".parse().unwrap());
            }
            Err(_) => return super::detail(403, "Administrator access required"),
        }
    } else if is_session {
        match auth::verify(s, incoming, method.as_str(), false).await {
            Ok(Some(user)) => {
                account_id = user["user_uuid_id"].as_str().unwrap_or_default().to_owned();
                if super::identity(s, &mut extra, &user).await.is_err() {
                    return super::detail(503, "Account information unavailable");
                }
            }
            Ok(None) | Err(_) => return super::detail(401, "Authentication required"),
        }
    }

    let ip_str = client_ip(peer, incoming).to_string();
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    let is_feedback = method == Method::POST
        && matches!(parts.as_slice(), ["me", "transcriptions", _, "feedback"]);
    let _feedback_guard = if is_feedback {
        if let Ok(n) = s
            .cache
            .increment(
                &format!("rl:annotations:feedback:user:{account_id}:60s"),
                60,
            )
            .await
            && n > FEEDBACK_RATE_PER_ACCOUNT_MINUTE
        {
            return super::detail(429, "Rate limit exceeded");
        }
        if let Ok(n) = s
            .cache
            .increment(&format!("rl:annotations:feedback:ip:{ip_str}:60s"), 60)
            .await
            && n > FEEDBACK_RATE_PER_IP_MINUTE
        {
            return super::detail(429, "Rate limit exceeded");
        }
        match acquire_feedback_slot(&account_id, &ip_str) {
            Some(guard) => Some(guard),
            None => return super::detail(429, "Too many concurrent feedback requests"),
        }
    } else {
        None
    };

    let mut headers = HeaderMap::new();
    for (key, value) in incoming {
        if !proxy::blocked(key.as_str())
            && !matches!(
                key.as_str(),
                "authorization"
                    | "cookie"
                    | "x-uuid"
                    | "x-access-level"
                    | "x-project-admin"
                    | "x-display-name"
                    | "x-forwarded-for"
                    | "cf-connecting-ip"
                    | "content-length"
            )
        {
            headers.append(key.clone(), value.clone());
        }
    }
    headers.extend(extra);
    headers.insert("x-forwarded-for", ip_str.parse().unwrap());

    let upload = method == Method::PUT
        && matches!(
            parts.as_slice(),
            ["me" | "admin", "files", _, "content"] | ["instant", _, "files", _, "content"]
        );
    let sse = method == Method::GET
        && (path == "/logs/stream"
            || matches!(
                parts.as_slice(),
                ["me", "transcriptions" | "content_jobs", _, "events"]
            ));
    let model_download = method == Method::GET
        && matches!(parts.as_slice(), ["me", "model_downloads", _, "content"]);

    let limit = if upload {
        50_000_000 + 65_536
    } else {
        2 * 1024 * 1024
    };
    if incoming
        .get("content-length")
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<usize>().ok())
        .is_some_and(|v| v > limit)
    {
        return super::detail(413, "Request body too large");
    }
    let Some(base) = s.settings.target("annotations") else {
        return super::detail(503, "Annotations unavailable");
    };
    let target = format!(
        "{}{path}{}",
        base.trim_end_matches('/'),
        query.map(|q| format!("?{q}")).unwrap_or_default()
    );
    let mut request = s.client.request(method.clone(), target).headers(headers);
    if !sse && !model_download {
        request = request.timeout(std::time::Duration::from_secs(300));
    } else if model_download {
        request = request.timeout(std::time::Duration::from_secs(3000));
    }

    let request = if upload {
        let mut received = 0usize;
        let stream = body.into_data_stream().map(move |chunk| {
            let chunk = chunk.map_err(std::io::Error::other)?;
            received = received.saturating_add(chunk.len());
            if received > limit {
                Err(std::io::Error::other("Upload exceeds limit"))
            } else {
                Ok(chunk)
            }
        });
        request.body(reqwest::Body::wrap_stream(stream))
    } else {
        match to_bytes(body, limit).await {
            Ok(bytes) => request.body(bytes),
            Err(_) => return super::detail(413, "Request body too large"),
        }
    };
    match request.send().await {
        Ok(upstream) => {
            let mut result = Response::new(Body::empty());
            *result.status_mut() = upstream.status();
            for (key, value) in upstream.headers() {
                if !proxy::blocked(key.as_str()) {
                    result.headers_mut().append(key.clone(), value.clone());
                }
            }
            if sse && !result.headers().contains_key("x-accel-buffering") {
                result
                    .headers_mut()
                    .insert("x-accel-buffering", "no".parse().unwrap());
            }
            result
                .headers_mut()
                .insert("cache-control", "no-store".parse().unwrap());
            *result.body_mut() = Body::from_stream(upstream.bytes_stream());
            result
        }
        Err(_) => super::detail(502, "Annotations unavailable"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn public_writes_are_only_waitlist_and_temporary_rooms() {
        assert!(public(&Method::GET, "/notes"));
        assert!(public(&Method::GET, "/notes/n1"));
        assert!(public(&Method::GET, "/authors/a1"));
        assert!(public(&Method::GET, "/authors/a1/projects"));
        assert!(public(&Method::GET, "/projects/p1"));
        assert!(public(&Method::POST, "/instant/a/files"));
        assert!(public(&Method::PUT, "/instant/a/files/f1/content"));
        assert!(public(&Method::PUT, "/instant/a"));
        assert!(public(&Method::PATCH, "/instant/a"));
        assert!(public(&Method::PUT, "/instant/a/items/b"));
        assert!(public(&Method::PATCH, "/instant/a/items/b"));
        assert!(public(&Method::DELETE, "/instant/a/items/b"));
        assert!(!public(&Method::DELETE, "/instant/a"));
        assert!(!public(&Method::GET, "/posts"));
        assert!(!public(&Method::GET, "/posts/a"));
        assert!(!public(&Method::GET, "/me/notes"));
        assert!(!public(&Method::GET, "/models"));
        assert!(!public(&Method::GET, "/models/v1"));
        assert!(!public(&Method::GET, "/logs/stream"));
        assert!(!public(&Method::GET, "/admin/notes/a"));
        assert!(!administrator("/admin/posts/a"));
        assert!(!administrator("/admin/images/a"));
        assert!(administrator("/admin/notes/a"));
        assert!(administrator("/logs/stream"));
        assert!(session("/models"));
        assert!(session("/models/v1"));
        assert!(session("/me/notes"));
        assert!(!session("/notes"));
    }
    #[test]
    fn only_loopback_proxy_can_supply_cloudflare_ip() {
        let mut h = HeaderMap::new();
        h.insert("cf-connecting-ip", "203.0.113.4".parse().unwrap());
        h.insert("x-forwarded-for", "203.0.113.99".parse().unwrap());
        assert_eq!(
            client_ip("127.0.0.1".parse().unwrap(), &h).to_string(),
            "203.0.113.4"
        );
        assert_eq!(
            client_ip("198.51.100.9".parse().unwrap(), &h).to_string(),
            "198.51.100.9"
        );
    }
}
