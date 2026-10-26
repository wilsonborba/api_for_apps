use serde_json::Value;
use std::{collections::HashMap, sync::Arc};
#[derive(Clone)]
pub struct Settings {
    pub values: Arc<HashMap<String, String>>,
    pub defaults: Arc<Value>,
}
impl Settings {
    pub fn load() -> Self {
        if std::env::var("TEST_SQLITE_PATH")
            .unwrap_or_default()
            .is_empty()
        {
            let _ = dotenvy::dotenv();
        }
        Self {
            values: Arc::new(std::env::vars().collect()),
            defaults: Arc::new(serde_json::from_str(include_str!("defaults.json")).unwrap()),
        }
    }
    pub fn validate_runtime(&self) -> anyhow::Result<()> {
        for key in [
            "API_KEY_SECRET",
            "SUPABASE_SECRET_KEY",
            "CERTIFICATIONS_SERVICE_KEY",
            "FERNET_KEY_SECRET",
            "SERVER_FERNET_KEY_SECRET",
        ] {
            anyhow::ensure!(
                self.values.contains_key(key),
                "Missing required setting: {key}"
            );
        }
        for key in ["FERNET_KEY_SECRET", "SERVER_FERNET_KEY_SECRET"] {
            anyhow::ensure!(
                fernet::Fernet::new(&self.get(key)).is_some(),
                "Invalid Fernet configuration: {key}"
            );
        }
        if self.get("TEST_SQLITE_PATH").is_empty() {
            for key in [
                "DEFAULT_DB_HOST",
                "DEFAULT_DB_PORT",
                "DEFAULT_DB_USER",
                "DEFAULT_DB_PASSWORD",
                "DEFAULT_DB_NAME",
            ] {
                anyhow::ensure!(
                    self.values.contains_key(key),
                    "Missing required setting: {key}"
                );
            }
        }
        if let Some(port) = self.values.get("DEFAULT_DB_PORT") {
            port.parse::<u16>()
                .map_err(|_| anyhow::anyhow!("Invalid DEFAULT_DB_PORT"))?;
        }
        for key in [
            "PUBLIC_PROXY_ROUTES",
            "FORCE_AUTH_PROXY_ROUTES",
            "ADMIN_PROTECTED_PROXY_ROUTES",
            "APP_EXCHANGE_ORIGINS",
            "EXCHANGE_ALLOWED_APPS",
            "OAUTH_PROVIDERS",
        ] {
            if let Some(value) = self.values.get(key) {
                serde_json::from_str::<Value>(value)
                    .map_err(|_| anyhow::anyhow!("Invalid JSON setting: {key}"))?;
            }
        }
        Ok(())
    }
    pub fn get(&self, k: &str) -> String {
        self.values
            .get(k)
            .cloned()
            .unwrap_or_else(|| match &self.defaults[k] {
                Value::String(s) => s.clone(),
                Value::Null => String::new(),
                v => v.to_string(),
            })
    }
    pub fn number(&self, k: &str, default: u64) -> u64 {
        self.get(k).parse().unwrap_or(default)
    }
    pub fn value(&self, k: &str) -> Value {
        self.values
            .get(k)
            .and_then(|s| serde_json::from_str(s).ok())
            .unwrap_or_else(|| self.defaults[k].clone())
    }
    pub fn production(&self) -> bool {
        !matches!(
            self.get("ENVIRONMENT").to_lowercase().as_str(),
            "" | "development" | "dev" | "local"
        )
    }
    pub fn auth_url(&self, reset: bool) -> String {
        format!(
            "{}/{}",
            self.get(if self.production() {
                "AUTH_APP_PROD_URL"
            } else {
                "AUTH_APP_LOCAL_URL"
            }),
            if reset { "reset-password" } else { "callback" }
        )
    }
    pub fn target(&self, app: &str) -> Option<String> {
        static APPS: std::sync::LazyLock<Value> =
            std::sync::LazyLock::new(|| serde_json::from_str(include_str!("apps.json")).unwrap());
        let entry = APPS.get(app)?;
        let port = if let Some(key) = entry["port_setting"].as_str() {
            self.number(key, entry["port"].as_u64()?)
        } else {
            entry["port"].as_u64()?
        };
        let key = format!("{}_UPSTREAM", app.to_uppercase());
        let override_ = self.get(&key);
        Some(if override_.is_empty() {
            format!("http://localhost:{port}")
        } else {
            override_
        })
    }
    pub fn matches(&self, table: &str, app: &str, method: &str, path: &str) -> bool {
        self.value(table)[app][method]
            .as_array()
            .is_some_and(|a| a.iter().any(|v| glob(v.as_str().unwrap_or(""), path)))
    }
    pub fn allowed_app(&self, app: &str) -> bool {
        self.value("EXCHANGE_ALLOWED_APPS")
            .as_array()
            .is_some_and(|a| a.iter().any(|v| v == app))
    }
    pub fn origin_app(&self, origin: &str) -> Option<String> {
        let v = self.value("APP_EXCHANGE_ORIGINS");
        for (app, origins) in v.as_object()? {
            if origins.as_array()?.iter().any(|v| v == origin) {
                return Some(app.clone());
            }
        }
        if !self.get("CORTEX_WEB_LOCAL_ORIGIN").is_empty()
            && origin == self.get("CORTEX_WEB_LOCAL_ORIGIN")
        {
            return Some("cortex".into());
        }
        None
    }
}
pub fn glob(pattern: &str, s: &str) -> bool {
    // Python fnmatch '*' includes slashes.
    let mut r = String::from("^");
    for c in pattern.chars() {
        match c {
            '*' => r.push_str(".*"),
            '?' => r.push('.'),
            _ => r.push_str(&regex::escape(&c.to_string())),
        }
    }
    r.push('$');
    regex::Regex::new(&r).is_ok_and(|r| r.is_match(s))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn annotations_upstream_uses_registered_and_overridable_listener() {
        let settings=Settings{values:Arc::new(HashMap::new()), defaults:Arc::new(serde_json::json!({}))};
        assert_eq!(settings.target("annotations").as_deref(),Some("http://localhost:8111"));
        let settings=Settings{values:Arc::new(HashMap::from([("ANNOTATIONS_UPSTREAM".into(),"http://127.0.0.1:19001".into())])),..settings};
        assert_eq!(settings.target("annotations").as_deref(),Some("http://127.0.0.1:19001"));
    }
    #[test]
    fn glob_matches_python_slashes() {
        assert!(glob("/projects/*", "/projects/a/files/b"));
        assert!(glob("*/logs*", "/nested/logs/stream"));
        assert!(!glob("/logs*", "/catalog"));
    }
}
