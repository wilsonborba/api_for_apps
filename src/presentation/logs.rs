use super::*;
use axum::response::sse::{Event, KeepAlive, Sse};
pub async fn stream(s: &State, h: &HeaderMap) -> Response {
    if let Err(e) = auth::verify(s, h, "GET", true).await {
        return detail(403, &e.to_string());
    }
    let mut receiver = s.logs.subscribe();
    let state = s.clone();
    let headers = h.clone();
    let events = async_stream::stream! {let mut check=tokio::time::interval(std::time::Duration::from_secs(10));loop{tokio::select!{entry=receiver.recv()=>match entry{Ok(line)=>yield Ok::<_,std::convert::Infallible>(Event::default().event("log").data(line)),Err(tokio::sync::broadcast::error::RecvError::Lagged(n))=>yield Ok(Event::default().event("gap").data(format!("{n} log entries skipped for slow consumer"))),Err(_)=>break},_=check.tick()=>{if auth::verify(&state,&headers,"GET",true).await.is_err(){break}}}}};
    Sse::new(events)
        .keep_alive(KeepAlive::default())
        .into_response()
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
 let (mut tx,mut rx)=socket.split();let (mut utx,mut urx)=upstream.split();let mut interval=tokio::time::interval(std::time::Duration::from_secs(10));
 loop{tokio::select!{
 msg=urx.next()=>match msg{Some(Ok(Up::Text(t)))=>{if tokio::time::timeout(std::time::Duration::from_secs(10),tx.send(axum::extract::ws::Message::Text(t.to_string().into()))).await.is_err(){break}},Some(Ok(Up::Binary(b)))=>{if tx.send(axum::extract::ws::Message::Binary(b)).await.is_err(){break}},Some(Ok(Up::Ping(b)))=>{if utx.send(Up::Pong(b)).await.is_err(){break}},Some(Ok(Up::Close(_)))|Some(Err(_))|None=>break,_=>{}},
 msg=rx.next()=>match msg{Some(Ok(axum::extract::ws::Message::Close(_)))|None|Some(Err(_))=>break,Some(Ok(axum::extract::ws::Message::Ping(b)))=>{if tx.send(axum::extract::ws::Message::Pong(b)).await.is_err(){break}},_=>{}},
 _=interval.tick()=>if auth::verify(&s,&h,"GET",true).await.is_err(){break}
 }}let _=utx.close().await;let _=tx.close().await;
 }).into_response()
}
