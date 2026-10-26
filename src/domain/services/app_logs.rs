//! Gateway-owned recording with two explicit, non-configurable safety locks.
use crate::{
    core::logs::{RECORDING_MAX_SECONDS, Redactor, SAVED_LOG_RETENTION_DAYS},
    dal::{local::app_logs::LogQuery, remote::log_source},
    domain::State,
};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::{task::AbortHandle, time::Instant};
#[derive(Clone)]
struct Active {
    app: String,
    token: String,
    started: DateTime<Utc>,
    expires: DateTime<Utc>,
    stop: AbortHandle,
}
#[derive(Default)]
pub struct Recorder {
    active: Mutex<Option<Active>>,
}
impl Recorder {
    pub fn list(&self) -> Value {
        let active = self.active.lock().unwrap();
        json!({"recordings":active.iter().map(|r|json!({"app_id":r.app,"started_at":r.started,"expires_at":r.expires})).collect::<Vec<_>>(),"max_recording_seconds":RECORDING_MAX_SECONDS,"retention_days":SAVED_LOG_RETENTION_DAYS})
    }
    pub fn stop(&self, app: &str) -> bool {
        let mut active = self.active.lock().unwrap();
        if active.as_ref().is_some_and(|r| r.app == app) {
            active.take().unwrap().stop.abort();
            true
        } else {
            false
        }
    }
    fn finish(&self, token: &str) {
        let mut active = self.active.lock().unwrap();
        if active.as_ref().is_some_and(|r| r.token == token) {
            active.take();
        }
    }
    pub async fn start(
        self: &Arc<Self>,
        state: State,
        app: &str,
    ) -> Result<Value, (u16, &'static str)> {
        if !log_source::registered_apps()
            .iter()
            .any(|(id, _)| id == app)
        {
            return Err((404, "Unknown registered app"));
        }
        if !state.db.log_app_active(app).await.map_err(|_| {
            (
                503,
                "App catalog unavailable; run the explicit catalog sync",
            )
        })? {
            return Err((404, "App is not active in the catalog"));
        }
        if self.active.lock().unwrap().is_some() {
            return Err((409, "One app can be recorded at a time"));
        }
        let source = log_source::open(&state, app)
            .await
            .map_err(|_| (503, "Log source unavailable"))?;
        let started = Utc::now();
        let expires = started + chrono::Duration::seconds(RECORDING_MAX_SECONDS as i64);
        let app = app.to_string();
        let token = uuid::Uuid::new_v4().to_string();
        let deadline = Instant::now() + Duration::from_secs(RECORDING_MAX_SECONDS);
        let (begin, ready) = tokio::sync::oneshot::channel();
        {
            let mut active = self.active.lock().unwrap();
            if active.is_some() {
                return Err((409, "One app can be recorded at a time"));
            }
            let owner = self.clone();
            let task_app = app.clone();
            let task_token = token.clone();
            let task = tokio::spawn(async move {
                if ready.await.is_err() {
                    return;
                }
                let result =
                    tokio::time::timeout_at(deadline, record(&state, &task_app, source)).await;
                owner.finish(&task_token);
                if matches!(result, Ok(Err(_))) {
                    tracing::warn!(app_id=%task_app,"Recording stopped because its storage is unavailable");
                }
            });
            *active = Some(Active {
                app: app.clone(),
                token,
                started,
                expires,
                stop: task.abort_handle(),
            });
        }
        let _ = begin.send(());
        Ok(
            json!({"app_id":app,"started_at":started,"expires_at":expires,"max_recording_seconds":RECORDING_MAX_SECONDS}),
        )
    }
}
async fn record(state: &State, app: &str, mut source: log_source::Source) -> anyhow::Result<()> {
    let redactor = Redactor::new(&state.settings);
    loop {
        match source.next().await {
            Ok(Some(event)) => {
                if event.gap {
                    state
                        .db
                        .insert_log(
                            app,
                            "WARNING",
                            &format!("Live stream gap: {}", redactor.clean(&event.line)),
                            Utc::now(),
                        )
                        .await?;
                    continue;
                }
                let line = redactor.clean(&strip_ansi(&event.line));
                state
                    .db
                    .insert_log(app, level(&line), &line, Utc::now())
                    .await?;
            }
            Ok(None) | Err(_) => {
                tokio::time::sleep(Duration::from_secs(1)).await;
                match log_source::open(state, app).await {
                    Ok(next) => source = next,
                    Err(_) => continue,
                }
            }
        }
    }
}
fn strip_ansi(raw: &str) -> String {
    static PATTERN: std::sync::OnceLock<regex::Regex> = std::sync::OnceLock::new();
    PATTERN
        .get_or_init(|| regex::Regex::new(r"\x1b\[[0-9;]*[A-Za-z]").unwrap())
        .replace_all(raw, "")
        .into_owned()
}
fn level(line: &str) -> &'static str {
    let words: Vec<_> = line
        .split(|c: char| c.is_whitespace() || c == '|')
        .filter(|v| !v.is_empty())
        .take(4)
        .collect();
    // The standard level is the second token; the legacy date/time format uses the third.
    for index in [1, 2, 0] {
        match words.get(index).copied() {
            Some("ERROR" | "CRITICAL") => return "ERROR",
            Some("WARN" | "WARNING") => return "WARNING",
            Some("DEBUG") => return "DEBUG",
            Some("INFO") => return "INFO",
            _ => {}
        }
    }
    "INFO"
}

pub async fn saved(state: &State, mut query: LogQuery) -> Result<Value, (u16, &'static str)> {
    if query.limit.is_some_and(|n| !(1..=200).contains(&n))
        || query
            .level
            .as_deref()
            .is_some_and(|v| !matches!(v, "DEBUG" | "INFO" | "WARNING" | "ERROR"))
        || matches!((query.from,query.to),(Some(from),Some(to)) if from>to)
    {
        return Err((422, "Invalid log filter"));
    }
    let cutoff = Utc::now() - chrono::Duration::days(SAVED_LOG_RETENTION_DAYS);
    query.from = Some(query.from.map(|at| at.max(cutoff)).unwrap_or(cutoff));
    let rows = state
        .db
        .saved_logs(&query)
        .await
        .map_err(|_| (503, "Saved logs unavailable"))?;
    Ok(json!({"items":rows,"retention_days":SAVED_LOG_RETENTION_DAYS}))
}
pub fn spawn_purger(state: State) -> tokio::task::JoinHandle<()> {
    tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_secs(600));
        loop {
            interval.tick().await;
            let cutoff = Utc::now() - chrono::Duration::days(SAVED_LOG_RETENTION_DAYS);
            if state.db.purge_logs_before(cutoff).await.is_err() {
                tracing::warn!("Saved log retention cleanup will retry");
            }
        }
    })
}
