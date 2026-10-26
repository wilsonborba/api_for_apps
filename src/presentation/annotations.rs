//! Explicit Annotations boundary. Trusted LAN services remain authentication-free.
use crate::domain::{State, auth, proxy};
use axum::{
    body::{Body, to_bytes},
    http::{HeaderMap, Method},
    response::Response,
};
use futures_util::StreamExt;
use std::net::IpAddr;

pub(super) fn public(method: &Method, path: &str) -> bool {
    let parts: Vec<_> = path.trim_start_matches('/').split('/').collect();
    matches!(
        (method.as_str(), parts.as_slice()),
        ("GET", ["health" | "ready" | "catalog" | "posts"])
            | ("GET", ["posts" | "media", _])
            | ("GET", ["links", "preview"])
            | ("POST", ["waitlist"])
            | ("GET" | "PUT", ["instant", _])
            | ("POST", ["instant", _, "items" | "files"])
            | ("GET", ["instant", _, "files", _])
    )
}
pub(super) fn client_ip(peer: IpAddr, headers: &HeaderMap) -> IpAddr {
    if peer.is_loopback() {
        auth::header(headers, "cf-connecting-ip")
            .parse()
            .unwrap_or(peer)
    } else {
        peer
    }
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
    let administrator = path.starts_with("/admin/");
    if !administrator && !public(method, path) {
        return super::detail(404, "Not Found");
    }
    let mut extra = HeaderMap::new();
    if administrator {
        match auth::verify(s, incoming, method.as_str(), true).await {
            Ok(Some(user)) => super::identity(&mut extra, &user),
            Ok(None) => {
                extra.insert("x-access-level", "1".parse().unwrap());
            }
            Err(_) => return super::detail(403, "Administrator access required"),
        }
    }
    let mut headers = HeaderMap::new();
    for (key, value) in incoming {
        if !proxy::blocked(key.as_str())
            && !matches!(
                key.as_str(),
                "authorization"
                    | "cookie"
                    | "x-access-level"
                    | "x-project-admin"
                    | "x-forwarded-for"
                    | "cf-connecting-ip"
                    | "content-length"
            )
        {
            headers.append(key.clone(), value.clone());
        }
    }
    headers.extend(extra);
    headers.insert(
        "x-forwarded-for",
        client_ip(peer, incoming).to_string().parse().unwrap(),
    );
    let upload = method == Method::POST && (path.ends_with("/files") || path == "/admin/images");
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
    let request = s
        .client
        .request(method.clone(), target)
        .headers(headers)
        .timeout(std::time::Duration::from_secs(300));
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
        assert!(public(&Method::POST, "/instant/a/files"));
        assert!(public(&Method::PUT, "/instant/a"));
        assert!(!public(&Method::PUT, "/admin/posts/a"));
        assert!(!public(&Method::POST, "/posts"));
        assert!(!public(&Method::GET, "/admin/posts/a"));
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
