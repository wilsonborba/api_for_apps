//! Read-only operational verification. Never executes schema changes or DML.
use super::database::Database;
use crate::domain::State;
use anyhow::{Result, bail};
use serde_json::{Value, json};
pub async fn check(state: &State) -> Result<Value> {
    let users = state.db.all("defaultdb_user").await?;
    let tickets = state.db.all("defaultdb_support_ticket").await?;
    let revisions = state.db.all("alembic_version").await?;
    let revision = revisions
        .first()
        .and_then(|v| v["version_num"].as_str())
        .unwrap_or("");
    if revision != "20260909_01" {
        bail!("Unrecognized existing migration revision; inspect before deployment")
    }
    if let Database::Pg(pool) = &state.db {
        let mut tx = pool.begin().await?;
        sqlx::query("SET TRANSACTION READ ONLY")
            .execute(&mut *tx)
            .await?;
        let _:Value=sqlx::query_scalar("SELECT jsonb_build_object('time', CAST($1 AS timestamp with time zone), 'active', CAST($2 AS boolean), 'role', CAST($3 AS integer))").bind("2026-10-25T00:00:00Z").bind("true").bind("3").fetch_one(&mut *tx).await?;
        tx.rollback().await?;
    }
    let cache = if let super::cache::Cache::Redis(c, _) = &state.cache {
        let mut c = c.clone();
        let pong: String = redis::cmd("PING").query_async(&mut c).await?;
        pong == "PONG"
    } else {
        true
    };
    Ok(
        json!({"users":users.len(),"support_tickets":tickets.len(),"migration_revision":revision,"cache_connected":cache,"support_store_available":state.support.available().await,"telemetry_store_available":state.telemetry.available().await,"read_only":true,"limitations":["No production write transaction executed","Provider mutation flows use local test doubles","SQLite does not validate PostgreSQL locking/concurrency"]}),
    )
}
