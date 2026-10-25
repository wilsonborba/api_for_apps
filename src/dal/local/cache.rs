use anyhow::Result;
use serde_json::Value;
use std::{
    collections::HashMap,
    sync::Arc,
    time::{Duration, Instant},
};
use tokio::sync::Mutex;
#[derive(Clone)]
pub enum Cache {
    Redis(redis::aio::ConnectionManager, String),
    Memory(Arc<Mutex<HashMap<String, (Value, Instant)>>>),
}
impl Cache {
    pub async fn new(url: &str, namespace: &str) -> Result<Self> {
        Ok(if url == "memory://" {
            Self::Memory(Default::default())
        } else {
            Self::Redis(
                redis::Client::open(url)?.get_connection_manager().await?,
                namespace.into(),
            )
        })
    }
    pub async fn get(&self, key: &str, consume: bool) -> Result<Option<Value>> {
        match self {
            Self::Redis(c, n) => {
                let mut c = c.clone();
                let b: Option<Vec<u8>> = redis::cmd(if consume { "GETDEL" } else { "GET" })
                    .arg(format!("{n}{key}"))
                    .query_async(&mut c)
                    .await?;
                Ok(b.map(|b| rmp_serde::from_slice(&b)).transpose()?)
            }
            Self::Memory(m) => {
                let mut m = m.lock().await;
                if consume {
                    Ok(m.remove(key).filter(|x| x.1 > Instant::now()).map(|x| x.0))
                } else {
                    Ok(m.get(key)
                        .filter(|x| x.1 > Instant::now())
                        .map(|x| x.0.clone()))
                }
            }
        }
    }
    pub async fn set(&self, key: &str, value: Value, ttl: u64, nx: bool) -> Result<bool> {
        match self {
            Self::Redis(c, n) => {
                let mut c = c.clone();
                let mut cmd = redis::cmd("SET");
                cmd.arg(format!("{n}{key}"))
                    .arg(rmp_serde::to_vec_named(&value)?)
                    .arg("EX")
                    .arg(ttl);
                if nx {
                    cmd.arg("NX");
                }
                let r: Option<String> = cmd.query_async(&mut c).await?;
                Ok(r.is_some())
            }
            Self::Memory(m) => {
                let mut m = m.lock().await;
                if nx && m.get(key).is_some_and(|v| v.1 > Instant::now()) {
                    return Ok(false);
                }
                m.insert(
                    key.into(),
                    (value, Instant::now() + Duration::from_secs(ttl)),
                );
                Ok(true)
            }
        }
    }
    pub async fn delete(&self, key: &str) -> Result<()> {
        match self {
            Self::Redis(c, n) => {
                let mut c = c.clone();
                let _: u64 = redis::cmd("DEL")
                    .arg(format!("{n}{key}"))
                    .query_async(&mut c)
                    .await?;
            }
            Self::Memory(m) => {
                m.lock().await.remove(key);
            }
        }
        Ok(())
    }
    pub async fn increment(&self, key: &str, ttl: u64) -> Result<u64> {
        match self {
            Self::Redis(c, n) => {
                let mut c = c.clone();
                let count: u64 = redis::cmd("INCR")
                    .arg(format!("{n}{key}"))
                    .query_async(&mut c)
                    .await?;
                if count == 1 {
                    let _: u64 = redis::cmd("EXPIRE")
                        .arg(format!("{n}{key}"))
                        .arg(ttl)
                        .query_async(&mut c)
                        .await?;
                }
                Ok(count)
            }
            Self::Memory(m) => {
                let mut m = m.lock().await;
                let e = m
                    .entry(key.into())
                    .or_insert((Value::from(0), Instant::now() + Duration::from_secs(ttl)));
                if e.1 <= Instant::now() {
                    *e = (Value::from(0), Instant::now() + Duration::from_secs(ttl))
                }
                let n = e.0.as_u64().unwrap_or(0) + 1;
                e.0 = Value::from(n);
                Ok(n)
            }
        }
    }
}
