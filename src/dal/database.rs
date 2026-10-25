use crate::core::settings::Settings;
use anyhow::{Result, bail};
use serde_json::{Value, json};
use sqlx::{Column, Row};
#[derive(Clone)]
pub enum Database {
    Pg(sqlx::PgPool),
    Sqlite(sqlx::SqlitePool),
}
impl Database {
    pub async fn new(s: &Settings) -> Result<Self> {
        let path = s.get("TEST_SQLITE_PATH");
        if !path.is_empty() {
            if !std::path::Path::new(&path).is_file() {
                bail!("SQLite fixture must already exist")
            }
            return Ok(Self::Sqlite(
                sqlx::SqlitePool::connect(&format!("sqlite://{path}")).await?,
            ));
        }
        let opts = sqlx::postgres::PgConnectOptions::new()
            .host(&s.get("DEFAULT_DB_HOST"))
            .port(s.number("DEFAULT_DB_PORT", 5432) as u16)
            .username(&s.get("DEFAULT_DB_USER"))
            .password(&s.get("DEFAULT_DB_PASSWORD"))
            .database(&s.get("DEFAULT_DB_NAME"))
            .ssl_mode(
                s.get("DEFAULT_DB_SSLMODE")
                    .parse()
                    .unwrap_or(sqlx::postgres::PgSslMode::Require),
            );
        Ok(Self::Pg(
            sqlx::postgres::PgPoolOptions::new()
                .max_connections(12)
                .connect_lazy_with(opts),
        ))
    }
    pub async fn all(&self, table: &str) -> Result<Vec<Value>> {
        if !matches!(
            table,
            "defaultdb_user" | "defaultdb_support_ticket" | "alembic_version"
        ) {
            bail!("Unsupported table")
        }
        match self {
            Self::Pg(p) => Ok(sqlx::query_scalar::<_, Value>(&format!(
                "SELECT to_jsonb(t) FROM {table} t"
            ))
            .fetch_all(p)
            .await?),
            Self::Sqlite(p) => {
                let rows = sqlx::query(&format!("SELECT * FROM {table}"))
                    .fetch_all(p)
                    .await?;
                Ok(rows
                    .into_iter()
                    .map(|r| {
                        let mut o = serde_json::Map::new();
                        for c in r.columns() {
                            let k = c.name();
                            let v = if k == "is_active" {
                                r.try_get::<i64, _>(k)
                                    .map(|x| json!(x != 0))
                                    .unwrap_or(Value::Null)
                            } else if matches!(k, "id" | "access_level")
                                && table == "defaultdb_user"
                            {
                                r.try_get::<i64, _>(k)
                                    .map(Value::from)
                                    .unwrap_or(Value::Null)
                            } else {
                                r.try_get::<String, _>(k)
                                    .map(Value::from)
                                    .unwrap_or(Value::Null)
                            };
                            o.insert(k.into(), v);
                        }
                        Value::Object(o)
                    })
                    .collect())
            }
        }
    }
    pub async fn find(&self, table: &str, key: &str, v: &Value) -> Result<Option<Value>> {
        Ok(self.all(table).await?.into_iter().find(|r| &r[key] == v))
    }
    pub async fn fields(&self) -> Result<Value> {
        match self {
            Self::Pg(p) => {
                let rows=sqlx::query("SELECT column_name,data_type FROM information_schema.columns WHERE table_name='defaultdb_user'").fetch_all(p).await?;
                let mut o = serde_json::Map::new();
                for r in rows {
                    o.insert(
                        r.get::<String, _>(0),
                        json!(r.get::<String, _>(1).to_uppercase()),
                    );
                }
                Ok(Value::Object(o))
            }
            Self::Sqlite(p) => {
                let rows = sqlx::query("PRAGMA table_info(defaultdb_user)")
                    .fetch_all(p)
                    .await?;
                let mut o = serde_json::Map::new();
                for r in rows {
                    o.insert(
                        r.get::<String, _>("name"),
                        json!(r.get::<String, _>("type")),
                    );
                }
                Ok(Value::Object(o))
            }
        }
    }
    pub async fn insert(&self, table: &str, v: &Value) -> Result<Value> {
        self.write(table, None, v).await
    }
    pub async fn update(&self, table: &str, id: &Value, v: &Value) -> Result<Value> {
        self.write(table, Some(id), v).await
    }
    async fn write(&self, table: &str, id: Option<&Value>, v: &Value) -> Result<Value> {
        if !matches!(table, "defaultdb_user" | "defaultdb_support_ticket") {
            bail!("Unsupported table")
        }
        let o = v
            .as_object()
            .ok_or_else(|| anyhow::anyhow!("Expected object"))?;
        for k in o.keys() {
            if !k.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
                bail!("Invalid column")
            }
        }
        match self {
            Self::Pg(p) => {
                let cols = self.fields_for(table).await?;
                let mut qb = sqlx::QueryBuilder::<sqlx::Postgres>::new(if id.is_some() {
                    format!("UPDATE {table} SET ")
                } else {
                    format!("INSERT INTO {table} (")
                });
                if id.is_none() {
                    qb.push(
                        o.keys()
                            .map(|s| format!("\"{s}\""))
                            .collect::<Vec<_>>()
                            .join(","),
                    )
                    .push(") SELECT ");
                }
                for (i, k) in o.keys().enumerate() {
                    if i > 0 {
                        qb.push(",");
                    }
                    if id.is_some() {
                        qb.push(format!("\"{k}\" = "));
                    }
                    let ty = cols.get(k).and_then(Value::as_str).unwrap_or("text");
                    if !ty.chars().all(|c| {
                        c.is_ascii_alphanumeric() || c == ' ' || c == '_' || c == '[' || c == ']'
                    }) {
                        bail!("Unsupported SQL type")
                    }
                    qb.push("CAST(")
                        .push_bind(if o[k].is_null() {
                            None
                        } else {
                            Some(
                                o[k].as_str()
                                    .map(str::to_owned)
                                    .unwrap_or_else(|| o[k].to_string()),
                            )
                        })
                        .push(format!(" AS {ty})"));
                }
                if let Some(id) = id {
                    let ty = if table == "defaultdb_user" {
                        "integer"
                    } else {
                        "text"
                    };
                    qb.push(" WHERE id = CAST(")
                        .push_bind(
                            id.as_str()
                                .map(str::to_owned)
                                .unwrap_or_else(|| id.to_string()),
                        )
                        .push(format!(" AS {ty})"));
                }
                qb.push(format!(" RETURNING to_jsonb({table}.*)"));
                Ok(qb.build_query_scalar::<Value>().fetch_one(p).await?)
            }
            Self::Sqlite(p) => {
                let keys: Vec<_> = o.keys().collect();
                let sql = if id.is_some() {
                    format!(
                        "UPDATE {table} SET {} WHERE id = ?",
                        keys.iter()
                            .map(|k| format!("\"{k}\"=?"))
                            .collect::<Vec<_>>()
                            .join(",")
                    )
                } else {
                    format!(
                        "INSERT INTO {table} ({}) VALUES ({})",
                        keys.iter()
                            .map(|k| format!("\"{k}\""))
                            .collect::<Vec<_>>()
                            .join(","),
                        vec!["?"; keys.len()].join(",")
                    )
                };
                let mut q = sqlx::query(&sql);
                for k in keys {
                    q = if o[k].is_boolean() {
                        q.bind(o[k].as_bool().map(|b| if b { 1i64 } else { 0 }))
                    } else if o[k].is_i64() {
                        q.bind(o[k].as_i64())
                    } else {
                        q.bind(if o[k].is_null() {
                            None
                        } else {
                            Some(
                                o[k].as_str()
                                    .map(str::to_owned)
                                    .unwrap_or_else(|| o[k].to_string()),
                            )
                        })
                    };
                }
                if let Some(id) = id {
                    q = q.bind(
                        id.as_str()
                            .map(str::to_owned)
                            .unwrap_or_else(|| id.to_string()),
                    );
                }
                let r = q.execute(p).await?;
                let id = id.cloned().unwrap_or_else(|| {
                    v.get("id").cloned().unwrap_or(json!(r.last_insert_rowid()))
                });
                Ok(self
                    .find(table, "id", &id)
                    .await?
                    .unwrap_or_else(|| v.clone()))
            }
        }
    }
    async fn fields_for(&self, table: &str) -> Result<Value> {
        if let Self::Pg(p) = self {
            let r = sqlx::query(
                "SELECT column_name,data_type FROM information_schema.columns WHERE table_name=$1",
            )
            .bind(table)
            .fetch_all(p)
            .await?;
            let mut o = serde_json::Map::new();
            for x in r {
                o.insert(x.get::<String, _>(0), json!(x.get::<String, _>(1)));
            }
            Ok(Value::Object(o))
        } else {
            Ok(json!({}))
        }
    }
}
