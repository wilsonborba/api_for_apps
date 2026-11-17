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
    /// Replace an unchanged, live record. Optionally create a second record in
    /// the same atomic operation. A missing TTL preserves the original expiry.
    /// The caller owns the transition rules; the adapter only compares bytes.
    pub async fn compare_and_swap(
        &self,
        key: &str,
        expected: &Value,
        replacement: Value,
        ttl: Option<u64>,
        insert: Option<(&str, Value, u64)>,
    ) -> Result<bool> {
        match self {
            Self::Redis(c, namespace) => {
                let mut c = c.clone();
                let script = r#"
                    if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
                    if ARGV[4] ~= '' and redis.call('EXISTS', KEYS[2]) == 1 then return 0 end
                    if ARGV[4] ~= '' then
                        redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[5], 'NX')
                    end
                    if ARGV[3] == '0' then
                        redis.call('SET', KEYS[1], ARGV[2], 'KEEPTTL')
                    else
                        redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
                    end
                    return 1
                "#;
                let (other_key, other_value, other_ttl) = match insert {
                    Some((key, value, ttl)) => (
                        format!("{namespace}{key}"),
                        rmp_serde::to_vec_named(&value)?,
                        ttl,
                    ),
                    None => (format!("{namespace}{key}"), Vec::new(), 0),
                };
                let changed: u8 = redis::cmd("EVAL")
                    .arg(script)
                    .arg(2)
                    .arg(format!("{namespace}{key}"))
                    .arg(other_key)
                    .arg(rmp_serde::to_vec_named(expected)?)
                    .arg(rmp_serde::to_vec_named(&replacement)?)
                    .arg(ttl.unwrap_or(0))
                    .arg(other_value)
                    .arg(other_ttl)
                    .query_async(&mut c)
                    .await?;
                Ok(changed == 1)
            }
            Self::Memory(m) => {
                let mut m = m.lock().await;
                let now = Instant::now();
                let Some((value, expires)) = m.get(key) else {
                    return Ok(false);
                };
                if *expires <= now || value != expected {
                    return Ok(false);
                }
                let expires = ttl
                    .map(|ttl| now + Duration::from_secs(ttl))
                    .unwrap_or(*expires);
                if let Some((other_key, value, ttl)) = insert {
                    if m.get(other_key).is_some_and(|entry| entry.1 > now) {
                        return Ok(false);
                    }
                    m.insert(other_key.into(), (value, now + Duration::from_secs(ttl)));
                }
                m.insert(key.into(), (replacement, expires));
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
