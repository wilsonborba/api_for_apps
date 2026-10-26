//! Fixed registered sources only. Legacy WebSocket apps stay supported.
use crate::domain::State;
use anyhow::{Result, bail};
use futures_util::{SinkExt, StreamExt};
use tokio::net::TcpStream;
use tokio::sync::broadcast;
use tokio_tungstenite::{MaybeTlsStream, WebSocketStream, tungstenite::Message};
#[derive(Clone)]
pub struct LogEvent {
    pub gap: bool,
    pub line: String,
}
pub enum Source {
    Local(broadcast::Receiver<String>),
    Sse {
        response: reqwest::Response,
        buffer: Vec<u8>,
    },
    WebSocket(Box<WebSocketStream<MaybeTlsStream<TcpStream>>>),
}
pub fn registered_apps() -> Vec<(String, String)> {
    let registry: serde_json::Value =
        serde_json::from_str(include_str!("../../core/apps.json")).unwrap();
    let mut apps: Vec<_> = registry
        .as_object()
        .unwrap()
        .keys()
        .map(|id| (id.clone(), id.clone()))
        .collect();
    apps.push(("api_for_apps".into(), "API for Apps".into()));
    apps
}
pub async fn open(state: &State, app: &str) -> Result<Source> {
    if app == "api_for_apps" {
        return Ok(Source::Local(state.logs.subscribe()));
    }
    let target = state
        .settings
        .target(app)
        .ok_or_else(|| anyhow::anyhow!("Unknown log source"))?;
    if matches!(app, "certifications" | "cortex") {
        let url = format!(
            "{}/logs/stream",
            target
                .trim_end_matches('/')
                .replacen("http://", "ws://", 1)
                .replacen("https://", "wss://", 1)
        );
        let (socket, _) = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            tokio_tungstenite::connect_async(url),
        )
        .await??;
        return Ok(Source::WebSocket(Box::new(socket)));
    }
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(std::time::Duration::from_secs(3))
        .build()?;
    let response = tokio::time::timeout(
        std::time::Duration::from_secs(5),
        client
            .get(format!("{}/logs/stream", target.trim_end_matches('/')))
            .header("accept", "text/event-stream")
            .send(),
    )
    .await??
    .error_for_status()?;
    if !response
        .headers()
        .get("content-type")
        .is_some_and(|v| v.to_str().unwrap_or("").starts_with("text/event-stream"))
    {
        bail!("Log source is not an SSE stream");
    }
    Ok(Source::Sse {
        response,
        buffer: Vec::new(),
    })
}
impl Source {
    pub async fn next(&mut self) -> Result<Option<LogEvent>> {
        match self {
            Self::Local(receiver) => match receiver.recv().await {
                Ok(line) => Ok(Some(LogEvent { gap: false, line })),
                Err(broadcast::error::RecvError::Lagged(count)) => Ok(Some(LogEvent {
                    gap: true,
                    line: format!("{count} log entries skipped"),
                })),
                Err(_) => Ok(None),
            },
            Self::WebSocket(socket) => loop {
                match socket.next().await {
                    Some(Ok(Message::Text(line))) => {
                        return Ok(Some(LogEvent {
                            gap: false,
                            line: line.to_string(),
                        }));
                    }
                    Some(Ok(Message::Ping(bytes))) => socket.send(Message::Pong(bytes)).await?,
                    Some(Ok(Message::Close(_))) | None => return Ok(None),
                    Some(Err(error)) => return Err(error.into()),
                    _ => {}
                }
            },
            Self::Sse { response, buffer } => loop {
                let lf = buffer.windows(2).position(|v| v == b"\n\n").map(|v| (v, 2));
                let crlf = buffer
                    .windows(4)
                    .position(|v| v == b"\r\n\r\n")
                    .map(|v| (v, 4));
                if let Some((end, separator)) =
                    lf.into_iter().chain(crlf).min_by_key(|(offset, _)| *offset)
                {
                    let frame = String::from_utf8(buffer[..end].to_vec())?;
                    buffer.drain(..end + separator);
                    let line = frame
                        .lines()
                        .filter_map(|line| {
                            line.strip_prefix("data:")
                                .map(|v| v.strip_prefix(' ').unwrap_or(v))
                        })
                        .collect::<Vec<_>>()
                        .join("\n");
                    if !line.is_empty() {
                        return Ok(Some(LogEvent {
                            gap: frame.lines().any(|l| l == "event: gap"),
                            line,
                        }));
                    }
                    continue;
                }
                let Some(bytes) = response.chunk().await? else {
                    return Ok(None);
                };
                if buffer.len() + bytes.len() > 65_536 {
                    bail!("Log source frame exceeded the bounded buffer");
                }
                buffer.extend_from_slice(&bytes);
            },
        }
    }
}
