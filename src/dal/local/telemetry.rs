//! Normalized SQL telemetry, transactions and idempotent event batches. No document columns.
use super::database::Database;
use crate::domain::services::telemetry::{ClientError, EventBatch};
use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::FromRow;
#[derive(FromRow, Serialize)]
pub struct SavedError {
    pub id: i64,
    pub app_id: String,
    pub session_id: String,
    pub user_id: Option<String>,
    pub route: String,
    pub error_type: String,
    pub message: String,
    pub stack: String,
    pub build_version: String,
    pub created_at: DateTime<Utc>,
}
#[derive(FromRow, Serialize)]
pub struct UsageSession {
    pub id: String,
    pub app_id: String,
    pub user_id: Option<String>,
    pub started_at: DateTime<Utc>,
    pub user_agent: String,
    pub ip: String,
    pub locale: String,
    pub theme: String,
    pub viewport_width: i32,
    pub viewport_height: i32,
}
#[derive(FromRow, Serialize)]
pub struct SavedEvent {
    pub id: i64,
    pub session_id: String,
    pub seq: i64,
    pub event_type: String,
    pub screen: String,
    pub route: String,
    pub path: String,
    pub element_id: String,
    pub element_label: String,
    pub element_path: String,
    pub value: Option<String>,
    pub created_at: DateTime<Utc>,
}
#[derive(serde::Deserialize, Default)]
#[serde(deny_unknown_fields)]
pub struct ReadQuery {
    pub app_id: Option<String>,
    pub session_id: Option<String>,
    pub from: Option<DateTime<Utc>>,
    pub to: Option<DateTime<Utc>>,
    pub limit: Option<i64>,
    pub before_id: Option<i64>,
}
macro_rules! write_error {($pool:expr,$v:expr,$user:expr)=>{{
    sqlx::query("INSERT INTO defaultdb_client_error(app_id,session_id,user_id,route,error_type,message,stack,build_version,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)")
    .bind(&$v.app_id).bind(&$v.session_id).bind($user).bind(&$v.route).bind(&$v.error_type).bind(&$v.message).bind(&$v.stack).bind(&$v.build_version).bind(Utc::now()).execute($pool).await?;
}}}
macro_rules! write_batch {($pool:expr,$v:expr,$user:expr,$ip:expr,$agent:expr)=>{{
    let mut tx=$pool.begin().await?;
    let now=Utc::now();
    let changed=sqlx::query("INSERT INTO defaultdb_usage_session(id,app_id,user_id,started_at,user_agent,ip,locale,theme,viewport_width,viewport_height) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(id) DO UPDATE SET user_id=excluded.user_id WHERE defaultdb_usage_session.app_id=excluded.app_id AND (defaultdb_usage_session.user_id IS NULL OR defaultdb_usage_session.user_id=excluded.user_id)")
    .bind(&$v.session_id).bind(&$v.app_id).bind($user).bind(now).bind($agent).bind($ip).bind(&$v.locale).bind(&$v.theme).bind($v.viewport_width).bind($v.viewport_height).execute(&mut *tx).await?.rows_affected();
    if changed==0 {anyhow::bail!("session_identity_changed");}
    let mut accepted=0;
    for event in &$v.events {
        accepted+=sqlx::query("INSERT INTO defaultdb_usage_event(session_id,seq,event_type,screen,route,path,element_id,element_label,element_path,value,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(session_id,seq) DO NOTHING")
        .bind(&$v.session_id).bind(event.seq).bind(&event.event_type).bind(&event.screen).bind(&event.route).bind(&event.path).bind(&event.element_id).bind(&event.element_label).bind(&event.element_path).bind(&event.value).bind(now).execute(&mut *tx).await?.rows_affected();
    }
    tx.commit().await?;
    accepted
}}}
macro_rules! read_rows {
    ($db:expr,$typ:ty,$sql:expr,$q:expr) => {{
        match $db {
            Database::Pg(pool) => {
                sqlx::query_as::<_, $typ>(
                    &$sql
                        .replace("$1 IS NULL", "$1::text IS NULL")
                        .replace("$2 IS NULL", "$2::text IS NULL")
                        .replace("$3 IS NULL", "$3::timestamptz IS NULL")
                        .replace("$4 IS NULL", "$4::timestamptz IS NULL")
                        .replace("$5 IS NULL", "$5::bigint IS NULL"),
                )
                .bind(&$q.app_id)
                .bind(&$q.session_id)
                .bind($q.from)
                .bind($q.to)
                .bind($q.before_id)
                .bind($q.limit.unwrap_or(100))
                .fetch_all(pool)
                .await?
            }
            Database::Sqlite(pool) => {
                sqlx::query_as::<_, $typ>($sql)
                    .bind(&$q.app_id)
                    .bind(&$q.session_id)
                    .bind($q.from)
                    .bind($q.to)
                    .bind($q.before_id)
                    .bind($q.limit.unwrap_or(100))
                    .fetch_all(pool)
                    .await?
            }
        }
    }};
}
impl Database {
    pub async fn telemetry_available(&self) -> bool {
        let sql = "SELECT e.id FROM defaultdb_client_error e JOIN defaultdb_usage_session s ON 1=0 JOIN defaultdb_usage_event u ON 1=0 LIMIT 0";
        match self {
            Self::Pg(pool) => sqlx::query(sql).fetch_all(pool).await.is_ok(),
            Self::Sqlite(pool) => sqlx::query(sql).fetch_all(pool).await.is_ok(),
        }
    }

    pub async fn insert_client_error(
        &self,
        v: &ClientError,
        user: Option<&str>,
    ) -> anyhow::Result<()> {
        match self {
            Self::Pg(pool) => write_error!(pool, v, user),
            Self::Sqlite(pool) => write_error!(pool, v, user),
        };
        Ok(())
    }
    pub async fn insert_event_batch(
        &self,
        v: &EventBatch,
        user: Option<&str>,
        ip: &str,
        agent: &str,
    ) -> anyhow::Result<u64> {
        Ok(match self {
            Self::Pg(pool) => write_batch!(pool, v, user, ip, agent),
            Self::Sqlite(pool) => write_batch!(pool, v, user, ip, agent),
        })
    }
    pub async fn client_errors(&self, q: &ReadQuery) -> anyhow::Result<Vec<SavedError>> {
        let sql = "SELECT id,app_id,session_id,user_id,route,error_type,message,stack,build_version,created_at FROM defaultdb_client_error WHERE ($1 IS NULL OR app_id=$1) AND ($2 IS NULL OR session_id=$2) AND ($3 IS NULL OR created_at>=$3) AND ($4 IS NULL OR created_at<=$4) AND ($5 IS NULL OR id<$5) ORDER BY id DESC LIMIT $6";
        Ok(read_rows!(self, SavedError, sql, q))
    }
    pub async fn usage_events(&self, q: &ReadQuery) -> anyhow::Result<Vec<SavedEvent>> {
        let sql = "SELECT e.id,e.session_id,e.seq,e.event_type,e.screen,e.route,e.path,e.element_id,e.element_label,e.element_path,e.value,e.created_at FROM defaultdb_usage_event e JOIN defaultdb_usage_session s ON s.id=e.session_id WHERE ($1 IS NULL OR s.app_id=$1) AND ($2 IS NULL OR e.session_id=$2) AND ($3 IS NULL OR e.created_at>=$3) AND ($4 IS NULL OR e.created_at<=$4) AND ($5 IS NULL OR e.id<$5) ORDER BY e.id DESC LIMIT $6";
        Ok(read_rows!(self, SavedEvent, sql, q))
    }
    pub async fn usage_sessions(&self, q: &ReadQuery) -> anyhow::Result<Vec<UsageSession>> {
        // Sessions use time ordering, not the numeric event/error cursor.
        let sql = "SELECT id,app_id,user_id,started_at,user_agent,ip,locale,theme,viewport_width,viewport_height FROM defaultdb_usage_session WHERE ($1 IS NULL OR app_id=$1) AND ($2 IS NULL OR id=$2) AND ($3 IS NULL OR started_at>=$3) AND ($4 IS NULL OR started_at<=$4) ORDER BY started_at DESC,id LIMIT $5";
        Ok(match self {
            Self::Pg(pool) => {
                sqlx::query_as::<_, UsageSession>(
                    &sql.replace("$1 IS NULL", "$1::text IS NULL")
                        .replace("$2 IS NULL", "$2::text IS NULL")
                        .replace("$3 IS NULL", "$3::timestamptz IS NULL")
                        .replace("$4 IS NULL", "$4::timestamptz IS NULL"),
                )
                .bind(&q.app_id)
                .bind(&q.session_id)
                .bind(q.from)
                .bind(q.to)
                .bind(q.limit.unwrap_or(100))
                .fetch_all(pool)
                .await?
            }
            Self::Sqlite(pool) => {
                sqlx::query_as::<_, UsageSession>(sql)
                    .bind(&q.app_id)
                    .bind(&q.session_id)
                    .bind(q.from)
                    .bind(q.to)
                    .bind(q.limit.unwrap_or(100))
                    .fetch_all(pool)
                    .await?
            }
        })
    }
}
