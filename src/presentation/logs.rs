use super::*;
use axum::response::sse::{Event, KeepAlive, Sse};
pub async fn stream(s: &State, h: &HeaderMap) -> Response {
    app_stream(s, h, "api_for_apps").await
}

pub async fn websocket(
    s: State,
    h: HeaderMap,
    app: String,
    suffix: String,
    upgrade: axum::extract::ws::WebSocketUpgrade,
) -> Response {
    if let Err(e) = auth::verify(&s, &h, "GET", true).await {
        return detail(403, &e.to_string());
    }
    let Some(target) = s.settings.target(&app) else {
        return detail(404, "Unknown log source");
    };
    // Only fixed existing application log endpoints are supported. No arbitrary target URL.
    let url = format!(
        "{}{}",
        target
            .replacen("http://", "ws://", 1)
            .replacen("https://", "wss://", 1),
        suffix
    );
    upgrade.on_upgrade(move|socket|async move{
 use futures_util::{SinkExt,StreamExt};use tokio_tungstenite::tungstenite::Message as Up;
 let upstream=tokio_tungstenite::connect_async(&url).await;
 let Ok((upstream,_))=upstream else{tracing::warn!(app,"Live log upstream connection failed");return};
 let redactor=crate::core::logs::Redactor::new(&s.settings);
 let (mut tx,mut rx)=socket.split();let (mut utx,mut urx)=upstream.split();let mut interval=tokio::time::interval(std::time::Duration::from_secs(10));
 loop{tokio::select!{
 msg=urx.next()=>match msg{Some(Ok(Up::Text(t)))=>{if tokio::time::timeout(std::time::Duration::from_secs(10),tx.send(axum::extract::ws::Message::Text(redactor.clean(&t).into()))).await.is_err(){break}},Some(Ok(Up::Binary(b)))=>{if tx.send(axum::extract::ws::Message::Binary(b)).await.is_err(){break}},Some(Ok(Up::Ping(b)))=>{if utx.send(Up::Pong(b)).await.is_err(){break}},Some(Ok(Up::Close(_)))|Some(Err(_))|None=>break,_=>{}},
 msg=rx.next()=>match msg{Some(Ok(axum::extract::ws::Message::Close(_)))|None|Some(Err(_))=>break,Some(Ok(axum::extract::ws::Message::Ping(b)))=>{if tx.send(axum::extract::ws::Message::Pong(b)).await.is_err(){break}},_=>{}},
 _=interval.tick()=>if auth::verify(&s,&h,"GET",true).await.is_err(){break}
 }}let _=utx.close().await;let _=tx.close().await;
 }).into_response()
}

/// All sources use this admin boundary, independent of environment policy overrides.
pub async fn app_stream(s: &State, h: &HeaderMap, app: &str) -> Response {
    if auth::verify(s, h, "GET", true).await.is_err() {
        return detail(403, "Administrator access required");
    }
    if !crate::dal::remote::log_source::registered_apps()
        .iter()
        .any(|(id, _)| id == app)
    {
        return detail(404, "Unknown log source");
    }
    let mut source = match crate::dal::remote::log_source::open(s, app).await {
        Ok(source) => source,
        Err(_) => return detail(503, "Log source unavailable"),
    };
    let state = s.clone();
    let headers = h.clone();
    let redactor = crate::core::logs::Redactor::new(&s.settings);
    let events = async_stream::stream! {
        let mut check=tokio::time::interval(std::time::Duration::from_secs(10));
        loop {tokio::select!{
            next=source.next()=>match next {
                Ok(Some(event))=>yield Ok::<_,std::convert::Infallible>(Event::default().event(if event.gap{"gap"}else{"log"}).data(redactor.clean(&event.line))),
                _=>break,
            },
            _=check.tick()=>if auth::verify(&state,&headers,"GET",true).await.is_err(){break}
        }}
    };
    let mut response = Sse::new(events)
        .keep_alive(KeepAlive::default())
        .into_response();
    response
        .headers_mut()
        .insert("cache-control", "no-store".parse().unwrap());
    response
        .headers_mut()
        .insert("x-accel-buffering", "no".parse().unwrap());
    response
}

pub fn app_stream_id(path: &str) -> Option<&str> {
    path.strip_prefix("/apps/")?
        .strip_suffix("/v1/logs/stream")
        .filter(|id| !id.is_empty() && !id.contains('/'))
}
pub fn recording_route(path: &str) -> bool {
    path == "/apps/api/v1/logs"
        || path == "/apps/api/v1/logs/recordings"
        || path.starts_with("/apps/api/v1/logs/recordings/")
}
pub async fn recording(
    s: &State,
    method: &Method,
    path: &str,
    query: Option<&str>,
    headers: &HeaderMap,
    body: axum::body::Body,
) -> Response {
    if auth::verify(s, headers, method.as_str(), true)
        .await
        .is_err()
    {
        return detail(403, "Administrator access required");
    }
    let result = if path == "/apps/api/v1/logs/recordings" {
        if method == Method::GET {
            Ok(s.recordings.list())
        } else if method == Method::POST {
            #[derive(serde::Deserialize)]
            #[serde(deny_unknown_fields)]
            struct Start {
                app_id: String,
            }
            let bytes = match axum::body::to_bytes(body, 4096).await {
                Ok(bytes) => bytes,
                Err(_) => return detail(413, "Recording request too large"),
            };
            let input: Start = match serde_json::from_slice(&bytes) {
                Ok(input) => input,
                Err(_) => return detail(422, "An app_id is required"),
            };
            s.recordings.start(s.clone(), &input.app_id).await
        } else {
            return detail(405, "Method Not Allowed");
        }
    } else if path == "/apps/api/v1/logs" {
        if method != Method::GET {
            return detail(405, "Method Not Allowed");
        }
        let query = match serde_urlencoded::from_str::<crate::dal::local::app_logs::LogQuery>(
            query.unwrap_or(""),
        ) {
            Ok(query) => query,
            Err(_) => return detail(422, "Invalid log filters"),
        };
        crate::domain::services::app_logs::saved(s, query).await
    } else if let Some(app) = path.strip_prefix("/apps/api/v1/logs/recordings/") {
        if method != Method::DELETE {
            return detail(405, "Method Not Allowed");
        }
        if !crate::dal::remote::log_source::registered_apps()
            .iter()
            .any(|(id, _)| id == app)
        {
            return detail(404, "Unknown app");
        }
        s.recordings.stop(app);
        Ok(json!({"app_id":app,"recording":false}))
    } else {
        return detail(404, "Not Found");
    };
    match result {
        Ok(value) => {
            let mut response = axum::Json(value).into_response();
            response
                .headers_mut()
                .insert("cache-control", "no-store".parse().unwrap());
            response
        }
        Err((status, message)) => detail(status, message),
    }
}
