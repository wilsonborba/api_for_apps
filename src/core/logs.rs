//! One line goes to journald and the live stream. Debug requires development mode.
use crate::core::settings::Settings;
use std::{
    fmt,
    io::{self, Write},
    sync::Arc,
};
use tokio::sync::broadcast;
use tracing::{
    Event, Subscriber,
    field::{Field, Visit},
};
use tracing_subscriber::{
    fmt::{FmtContext, FormatEvent, FormatFields, format::Writer},
    registry::LookupSpan,
};

pub const APP: &str = "api_for_apps";
pub const MAX_LOG_LINE_BYTES: usize = 16_384;
/// Deliberate safety lock. Removing it requires an explicit owner decision.
pub const RECORDING_MAX_SECONDS: u64 = 30 * 60;
/// Deliberate safety lock. Saved rows older than this are purged.
pub const SAVED_LOG_RETENTION_DAYS: i64 = 15;

#[derive(Clone)]
pub struct Redactor {
    secrets: Arc<Vec<String>>,
}
impl Redactor {
    pub fn new(settings: &Settings) -> Self {
        let mut secrets: Vec<String> = settings
            .values
            .iter()
            .filter(|(key, value)| {
                let key = key.to_ascii_uppercase();
                value.len() >= 3
                    && (key.contains("PASSWORD")
                        || key.contains("SECRET")
                        || key.ends_with("_API_KEY")
                        || key.ends_with("_TOKEN"))
            })
            .map(|(_, value)| value.clone())
            .collect();
        secrets.sort_by_key(|value| std::cmp::Reverse(value.len()));
        Self {
            secrets: Arc::new(secrets),
        }
    }
    pub fn clean(&self, raw: &str) -> String {
        let mut value = raw.replace(['\r', '\n'], "\\n");
        for secret in self.secrets.iter() {
            value = value.replace(secret, "[redacted]");
        }
        static PATTERNS: std::sync::LazyLock<Vec<(regex::Regex, &'static str)>> =
            std::sync::LazyLock::new(|| {
                vec![
            (regex::Regex::new(r"(?i)(bearer\s+)[^\s,;]+").unwrap(), "${1}[redacted]"),
            (regex::Regex::new(r#"(?i)((?:"|')?(?:password|passwd|secret|token|authorization|cookie|csrf|api[_-]?key)(?:"|')?\s*[=:]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)"#).unwrap(), "${1}[redacted]"),
            (regex::Regex::new(r"(https?://|postgres(?:ql)?://|redis://)[^/@\s]+@").unwrap(), "${1}[redacted]@"),
            (regex::Regex::new(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+").unwrap(), "[redacted]"),
        ]
            });
        for (pattern, replacement) in PATTERNS.iter() {
            value = pattern.replace_all(&value, *replacement).into_owned();
        }
        if value.len() > MAX_LOG_LINE_BYTES {
            let mut end = MAX_LOG_LINE_BYTES;
            while !value.is_char_boundary(end) {
                end -= 1;
            }
            value.truncate(end);
        }
        value
    }
}
#[derive(Clone)]
pub struct LineFormat {
    pub development: bool,
    pub redactor: Redactor,
}
#[derive(Default)]
struct Fields {
    message: String,
    fields: Vec<String>,
    module: Option<String>,
}
impl Visit for Fields {
    fn record_debug(&mut self, field: &Field, value: &dyn fmt::Debug) {
        let key = field.name();
        let value = format!("{value:?}");
        if key == "message" {
            self.message = value;
        } else if key == "module" {
            self.module = Some(value.trim_matches('"').to_owned());
        } else if [
            "password",
            "token",
            "secret",
            "cookie",
            "authorization",
            "api_key",
        ]
        .iter()
        .any(|word| key.to_ascii_lowercase().contains(word))
        {
            self.fields.push(format!("{key}=[redacted]"));
        } else {
            self.fields.push(format!("{key}={value}"));
        }
    }
}
impl<S, N> FormatEvent<S, N> for LineFormat
where
    S: Subscriber + for<'a> LookupSpan<'a>,
    N: for<'a> FormatFields<'a> + 'static,
{
    fn format_event(
        &self,
        _: &FmtContext<'_, S, N>,
        mut writer: Writer<'_>,
        event: &Event<'_>,
    ) -> fmt::Result {
        if *event.metadata().level() == tracing::Level::DEBUG && !self.development {
            return Ok(());
        }
        let level = if *event.metadata().level() == tracing::Level::WARN {
            "WARNING"
        } else {
            event.metadata().level().as_str()
        };
        let mut fields = Fields::default();
        event.record(&mut fields);
        let module = fields
            .module
            .as_deref()
            .unwrap_or(event.metadata().module_path().unwrap_or("gateway"));
        let module = self
            .redactor
            .clean(module)
            .replace(char::is_whitespace, "_");
        let message = if fields.fields.is_empty() {
            fields.message
        } else {
            format!("{} {}", fields.message, fields.fields.join(" "))
        };
        writeln!(
            writer,
            "{} {level} {APP} {module} {}",
            chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
            self.redactor.clean(&message)
        )
    }
}
#[derive(Clone)]
pub struct LogWriter(pub broadcast::Sender<String>);
pub struct LineWriter {
    sender: broadcast::Sender<String>,
    buffer: Vec<u8>,
}
impl Write for LineWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        io::stderr().write_all(bytes)?;
        for &byte in bytes {
            if byte == b'\n' {
                if !self.buffer.is_empty() {
                    let _ = self
                        .sender
                        .send(String::from_utf8_lossy(&self.buffer).into_owned());
                }
                self.buffer.clear();
            } else if self.buffer.len() < MAX_LOG_LINE_BYTES + 1024 {
                self.buffer.push(byte);
            }
        }
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        io::stderr().flush()
    }
}
impl<'a> tracing_subscriber::fmt::MakeWriter<'a> for LogWriter {
    type Writer = LineWriter;
    fn make_writer(&'a self) -> Self::Writer {
        LineWriter {
            sender: self.0.clone(),
            buffer: Vec::new(),
        }
    }
}
pub fn init(settings: &Settings, logs: broadcast::Sender<String>) {
    tracing_subscriber::fmt()
        .with_ansi(false)
        .with_max_level(if settings.development() {
            tracing::Level::DEBUG
        } else {
            tracing::Level::INFO
        })
        .event_format(LineFormat {
            development: settings.development(),
            redactor: Redactor::new(settings),
        })
        .with_writer(LogWriter(logs))
        .init();
}
#[allow(dead_code)]
pub fn debug(module: &str, message: &str) {
    tracing::debug!(module, message);
}
#[allow(dead_code)]
pub fn info(module: &str, message: &str) {
    tracing::info!(module, message);
}
#[allow(dead_code)]
pub fn warning(module: &str, message: &str) {
    tracing::warn!(module, message);
}
#[allow(dead_code)]
pub fn error(module: &str, message: &str) {
    tracing::error!(module, message);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{collections::HashMap, sync::Mutex};
    #[derive(Clone)]
    struct Capture(Arc<Mutex<Vec<u8>>>);
    impl Write for Capture {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.0.lock().unwrap().extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    fn settings() -> Settings {
        Settings {
            values: Arc::new(HashMap::from([
                ("API_KEY_SECRET".into(), "fixture-sensitive-secret".into()),
                ("DATABASE_PASSWORD".into(), "fixture-sensitive".into()),
            ])),
            defaults: Arc::new(serde_json::json!({})),
        }
    }
    #[test]
    fn line_format_gates_debug_normalizes_warning_and_redacts_before_output() {
        let bytes = Arc::new(Mutex::new(Vec::new()));
        let capture = Capture(bytes.clone());
        let subscriber = tracing_subscriber::fmt()
            .with_ansi(false)
            .with_max_level(tracing::Level::DEBUG)
            .event_format(LineFormat {
                development: false,
                redactor: Redactor::new(&settings()),
            })
            .with_writer(move || capture.clone())
            .finish();
        tracing::subscriber::with_default(subscriber, || {
            debug("test", "must not appear");
            info("test", "ready");
            warning("test", "line one\nline two");
            tracing::error!(
                module = "test",
                cookie = "raw-cookie",
                password = "raw-password",
                "credential fixture-sensitive-secret"
            );
        });
        let output = String::from_utf8(bytes.lock().unwrap().clone()).unwrap();
        let lines: Vec<_> = output.lines().collect();
        assert_eq!(lines.len(), 3);
        for (line, level) in lines.iter().zip(["INFO", "WARNING", "ERROR"]) {
            let fields: Vec<_> = line.splitn(5, ' ').collect();
            assert_eq!(fields.len(), 5);
            assert!(chrono::DateTime::parse_from_rfc3339(fields[0]).is_ok());
            assert_eq!(fields[1], level);
            assert_eq!(fields[2], APP);
            assert_eq!(fields[3], "test");
        }
        assert!(!output.contains("must not appear"));
        assert!(!output.contains("raw-cookie"));
        assert!(!output.contains("raw-password"));
        assert!(!output.contains("fixture-sensitive"));
        assert!(output.contains("line one\\nline two"));
    }
    #[test]
    fn redaction_handles_quoted_values_urls_and_utf8_bounds() {
        let redactor = Redactor::new(&settings());
        let result = redactor
            .clean("password='two words'; token=abc Bearer xyz postgres://user:pass@localhost/db");
        assert!(!result.contains("two words"));
        assert!(!result.contains("abc"));
        assert!(!result.contains("xyz"));
        assert!(!result.contains("user:pass"));
        assert!(
            !redactor
                .clean(r#"{"token":"raw-json-token"}"#)
                .contains("raw-json-token")
        );
        let bounded = redactor.clean(&"ไทย".repeat(10000));
        assert!(bounded.len() <= MAX_LOG_LINE_BYTES);
        assert!(std::str::from_utf8(bounded.as_bytes()).is_ok());
    }
}
