use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};
use tokio::sync::Mutex;
#[derive(Clone)]
pub struct Documents {
    client: reqwest::Client,
    url: String,
    user: String,
    password: String,
    prefix: String,
    memory: Arc<Mutex<BTreeMap<String, Value>>>,
}
impl Documents {
    pub async fn new(
        s: &crate::core::settings::Settings,
        kind: &str,
        client: reqwest::Client,
    ) -> Self {
        let mut url = s.get(&format!("{kind}_COUCHDB_URL"));
        let mut user = s.get(&format!("{kind}_COUCHDB_USERNAME"));
        let mut password = s.get(&format!("{kind}_COUCHDB_PASSWORD"));
        if kind == "TELEMETRY" && url.is_empty() {
            url = s.get("SUPPORT_COUCHDB_URL");
            user = s.get("SUPPORT_COUCHDB_USERNAME");
            password = s.get("SUPPORT_COUCHDB_PASSWORD");
        }
        if !url.is_empty() {
            url = format!(
                "{}/{}",
                url.trim_end_matches('/'),
                s.get(&format!("{kind}_COUCHDB_DATABASE"))
            );
            if !client
                .get(&url)
                .basic_auth(&user, Some(&password))
                .send()
                .await
                .is_ok_and(|r| r.status().is_success())
            {
                tracing::warn!(
                    kind,
                    "CouchDB unavailable; using existing memory fallback behavior"
                );
                url.clear();
            }
        }
        Self {
            client,
            url,
            user,
            password,
            prefix: if kind == "SUPPORT" {
                "ticket:"
            } else {
                "error:"
            }
            .into(),
            memory: Default::default(),
        }
    }
    fn req(&self, method: reqwest::Method, url: &str) -> reqwest::RequestBuilder {
        self.client
            .request(method, url)
            .basic_auth(&self.user, Some(&self.password))
    }
    pub async fn get(&self, id: &str) -> Option<Value> {
        if self.url.is_empty() {
            return self.memory.lock().await.get(id).cloned();
        }
        self.req(
            reqwest::Method::GET,
            &format!("{}/{}{id}", self.url, self.prefix),
        )
        .send()
        .await
        .ok()?
        .error_for_status()
        .ok()?
        .json()
        .await
        .ok()
    }
    pub async fn put(&self, id: &str, mut v: Value) -> bool {
        if self.url.is_empty() {
            self.memory.lock().await.insert(id.into(), v);
            return true;
        }
        let url = format!("{}/{}{id}", self.url, self.prefix);
        if let Some(old) = self.get(id).await {
            v["_rev"] = old["_rev"].clone();
        }
        v["_id"] = json!(format!("{}{id}", self.prefix));
        self.req(reqwest::Method::PUT, &url)
            .json(&v)
            .send()
            .await
            .is_ok_and(|r| r.status().is_success())
    }
    pub async fn recent(&self, limit: usize, skip: usize) -> Vec<Value> {
        if self.url.is_empty() {
            let mut v = self
                .memory
                .lock()
                .await
                .values()
                .cloned()
                .collect::<Vec<_>>();
            v.sort_by(|a, b| {
                b["server_timestamp"]
                    .as_str()
                    .cmp(&a["server_timestamp"].as_str())
            });
            return v.into_iter().skip(skip).take(limit).collect();
        }
        let r = self
            .req(reqwest::Method::GET, &format!("{}/_all_docs", self.url))
            .query(&[
                ("include_docs", "true".to_owned()),
                ("descending", "true".into()),
                ("limit", limit.to_string()),
                ("skip", skip.to_string()),
            ])
            .send()
            .await;
        if let Ok(r) = r
            && let Ok(v) = r.json::<Value>().await
        {
            return v["rows"]
                .as_array()
                .map(|a| a.iter().filter_map(|x| x.get("doc").cloned()).collect())
                .unwrap_or_default();
        }
        vec![]
    }
    pub async fn available(&self) -> bool {
        self.url.is_empty()
            || self
                .req(reqwest::Method::GET, &self.url)
                .send()
                .await
                .is_ok_and(|r| r.status().is_success())
    }
}
