//! Relational log storage. Only the gateway writes appdb records.
use super::database::Database;
use anyhow::Result;
use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::FromRow;
#[derive(Debug, Serialize, FromRow)]
pub struct SavedLog {
    pub id: i64,
    pub app_id: String,
    pub level: String,
    pub message: String,
    pub created_at: DateTime<Utc>,
}
#[derive(Default, serde::Deserialize)]
pub struct LogQuery {
    pub app_id: Option<String>,
    pub level: Option<String>,
    pub from: Option<DateTime<Utc>>,
    pub to: Option<DateTime<Utc>>,
    pub limit: Option<i64>,
}
impl Database {
    pub async fn sync_log_apps(&self, apps: &[(String, String)]) -> Result<()> {
        for (id, name) in apps {
            let sql = "INSERT INTO defaultdb_app(id,name,is_active) VALUES($1,$2,TRUE) ON CONFLICT(id) DO UPDATE SET name=excluded.name";
            match self {
                Self::Pg(pool) => {
                    sqlx::query(sql).bind(id).bind(name).execute(pool).await?;
                }
                Self::Sqlite(pool) => {
                    sqlx::query(sql).bind(id).bind(name).execute(pool).await?;
                }
            }
        }
        Ok(())
    }
    pub async fn log_app_active(&self, app: &str) -> Result<bool> {
        let sql = "SELECT is_active FROM defaultdb_app WHERE id=$1";
        Ok(match self {
            Self::Pg(pool) => {
                sqlx::query_scalar::<_, bool>(sql)
                    .bind(app)
                    .fetch_optional(pool)
                    .await?
            }
            Self::Sqlite(pool) => {
                sqlx::query_scalar::<_, bool>(sql)
                    .bind(app)
                    .fetch_optional(pool)
                    .await?
            }
        }
        .unwrap_or(false))
    }
    pub async fn insert_log(
        &self,
        app: &str,
        level: &str,
        message: &str,
        at: DateTime<Utc>,
    ) -> Result<()> {
        let sql =
            "INSERT INTO defaultdb_app_log(app_id,level,message,created_at) VALUES($1,$2,$3,$4)";
        match self {
            Self::Pg(pool) => {
                sqlx::query(sql)
                    .bind(app)
                    .bind(level)
                    .bind(message)
                    .bind(at)
                    .execute(pool)
                    .await?;
            }
            Self::Sqlite(pool) => {
                sqlx::query(sql)
                    .bind(app)
                    .bind(level)
                    .bind(message)
                    .bind(at)
                    .execute(pool)
                    .await?;
            }
        }
        Ok(())
    }
    pub async fn saved_logs(&self, q: &LogQuery) -> Result<Vec<SavedLog>> {
        let sql = "SELECT id,app_id,level,message,created_at FROM defaultdb_app_log WHERE ($1 IS NULL OR app_id=$1) AND ($2 IS NULL OR level=$2) AND ($3 IS NULL OR created_at>=$3) AND ($4 IS NULL OR created_at<=$4) ORDER BY id DESC LIMIT $5";
        Ok(match self {
            Self::Pg(pool) => {
                sqlx::query_as::<_, SavedLog>(
                    &sql.replace("$1 IS NULL", "$1::text IS NULL")
                        .replace("$2 IS NULL", "$2::text IS NULL")
                        .replace("$3 IS NULL", "$3::timestamptz IS NULL")
                        .replace("$4 IS NULL", "$4::timestamptz IS NULL"),
                )
                .bind(&q.app_id)
                .bind(&q.level)
                .bind(q.from)
                .bind(q.to)
                .bind(q.limit.unwrap_or(100))
                .fetch_all(pool)
                .await?
            }
            Self::Sqlite(pool) => {
                sqlx::query_as::<_, SavedLog>(sql)
                    .bind(&q.app_id)
                    .bind(&q.level)
                    .bind(q.from)
                    .bind(q.to)
                    .bind(q.limit.unwrap_or(100))
                    .fetch_all(pool)
                    .await?
            }
        })
    }
    pub async fn purge_logs_before(&self, cutoff: DateTime<Utc>) -> Result<u64> {
        let sql = "DELETE FROM defaultdb_app_log WHERE created_at<$1";
        Ok(match self {
            Self::Pg(pool) => sqlx::query(sql)
                .bind(cutoff)
                .execute(pool)
                .await?
                .rows_affected(),
            Self::Sqlite(pool) => sqlx::query(sql)
                .bind(cutoff)
                .execute(pool)
                .await?
                .rows_affected(),
        })
    }
}
