use super::State;
use anyhow::{Result, bail};
use serde_json::{Value, json};
pub fn timestamp() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}
fn message(body: &Value, admin: bool) -> Value {
    json!({"id":uuid::Uuid::new_v4().to_string(),"sender":if admin{"admin"}else{"user"},"body":body["body"].as_str().unwrap_or("").trim(),"attachment_reference":body["attachment_reference"],"timestamp":timestamp(),"read":false})
}
pub async fn require(s: &State, id: &str, user: &str, admin: bool) -> Result<Value> {
    let t =
        s.db.find("defaultdb_support_ticket", "id", &json!(id))
            .await?
            .ok_or_else(|| anyhow::anyhow!("Support ticket not found."))?;
    if !admin && t["user_id"] != user {
        bail!("Support ticket not found.")
    }
    Ok(t)
}
pub async fn create(s: &State, u: &Value, b: &Value) -> Result<Value> {
    let id = uuid::Uuid::new_v4().to_string();
    let now = timestamp();
    let mut t=s.db.insert("defaultdb_support_ticket",&json!({"id":id,"user_id":u["user_uuid_id"],"source_app":b["source_app"].as_str().unwrap_or("").trim().to_lowercase(),"status":"open","created_at":now,"updated_at":now})).await?;
    let m = message(b, false);
    let doc = json!({"ticket_id":id,"subject":b["subject"].as_str().map(str::trim),"messages":[m],"extra":{}});
    if !s.support.put(&id, doc.clone()).await {
        tracing::warn!("Support opening message storage failed")
    };
    t["subject"] = doc["subject"].clone();
    t["messages"] = doc["messages"].clone();
    Ok(t)
}
pub async fn get(s: &State, id: &str, u: &Value) -> Result<Value> {
    let mut t = require(
        s,
        id,
        u["user_uuid_id"].as_str().unwrap_or(""),
        u["access_level"] == 1,
    )
    .await?;
    let d = s.support.get(id).await.unwrap_or(json!({}));
    t["subject"] = d["subject"].clone();
    t["messages"] = d.get("messages").cloned().unwrap_or(json!([]));
    t["extra"] = d.get("extra").cloned().unwrap_or(json!({}));
    t["messages_available"] = json!(s.support.available().await);
    Ok(t)
}
pub async fn reply(s: &State, id: &str, u: &Value, b: &Value) -> Result<Value> {
    require(
        s,
        id,
        u["user_uuid_id"].as_str().unwrap_or(""),
        u["access_level"] == 1,
    )
    .await?;
    let mut doc = s
        .support
        .get(id)
        .await
        .unwrap_or(json!({"ticket_id":id,"subject":null,"messages":[],"extra":{}}));
    let m = message(b, u["access_level"] == 1);
    doc["messages"]
        .as_array_mut()
        .ok_or_else(|| anyhow::anyhow!("Invalid thread"))?
        .push(m.clone());
    let stored = s.support.put(id, doc).await;
    s.db.update(
        "defaultdb_support_ticket",
        &json!(id),
        &json!({"updated_at":timestamp()}),
    )
    .await?;
    if !stored {
        bail!("Support ticket message could not be stored")
    }
    Ok(m)
}
pub async fn mark(s: &State, id: &str, mid: Option<&str>, u: &Value) -> Result<Value> {
    require(
        s,
        id,
        u["user_uuid_id"].as_str().unwrap_or(""),
        u["access_level"] == 1,
    )
    .await?;
    let Some(mut doc) = s.support.get(id).await else {
        return Ok(json!({"count":0,"found":false}));
    };
    let mut count = 0;
    let mut found = false;
    if let Some(ms) = doc["messages"].as_array_mut() {
        for m in ms {
            if mid.is_none_or(|id| m["id"] == id) {
                found = true;
                if m["read"] != true {
                    m["read"] = json!(true);
                    count += 1;
                }
            }
        }
    }
    if count > 0 {
        let _ = s.support.put(id, doc).await;
        s.db.update(
            "defaultdb_support_ticket",
            &json!(id),
            &json!({"updated_at":timestamp()}),
        )
        .await?;
    }
    Ok(json!({"count":count,"found":found}))
}
