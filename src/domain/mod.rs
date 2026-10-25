pub mod auth;
pub mod proxy;
pub mod support;
use crate::{
    core::settings::Settings,
    dal::{cache::Cache, database::Database, documents::Documents},
};
#[derive(Clone)]
pub struct State {
    pub settings: Settings,
    pub cache: Cache,
    pub db: Database,
    pub support: Documents,
    pub telemetry: Documents,
    pub client: reqwest::Client,
    pub logs: tokio::sync::broadcast::Sender<String>,
}
impl State {
    pub async fn new(
        settings: Settings,
        logs: tokio::sync::broadcast::Sender<String>,
    ) -> anyhow::Result<Self> {
        if !settings.get("TEST_SQLITE_PATH").is_empty() {
            for key in [
                "SUPABASE_URL",
                "FSM_MEDIA_ENDPOINT",
                "SUPPORT_COUCHDB_URL",
                "TELEMETRY_COUCHDB_URL",
            ] {
                let value = settings.get(key);
                if value.is_empty() {
                    continue;
                }
                let url = url::Url::parse(&value)?;
                anyhow::ensure!(
                    matches!(url.host_str(), Some("localhost" | "127.0.0.1"))
                        && url.port().is_some_and(|p| (18000..19000).contains(&p)),
                    "Fixture network target must use an isolated loopback port: {key}"
                );
            }
            let cache = settings.get("REDIS_URL");
            if cache != "memory://" {
                let url = url::Url::parse(&cache)?;
                anyhow::ensure!(
                    matches!(url.host_str(), Some("localhost" | "127.0.0.1"))
                        && url.port().is_some_and(|p| (18000..19000).contains(&p)),
                    "Fixture Redis target must be isolated"
                );
            }
            for app in [
                "certifications",
                "cortex",
                "domain",
                "wilson_borba",
                "reports",
            ] {
                let url = url::Url::parse(&settings.target(app).unwrap())?;
                anyhow::ensure!(
                    matches!(url.host_str(), Some("localhost" | "127.0.0.1"))
                        && url.port().is_some_and(|p| (18000..19000).contains(&p)),
                    "Fixture upstream must be isolated: {app}"
                );
            }
        }
        let client = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(std::time::Duration::from_secs(2))
            .timeout(std::time::Duration::from_secs(20))
            .build()?;
        Ok(Self {
            cache: Cache::new(&settings.get("REDIS_URL"), &settings.get("REDIS_NAMESPACE")).await?,
            db: Database::new(&settings).await?,
            support: Documents::new(&settings, "SUPPORT", client.clone()).await,
            telemetry: Documents::new(&settings, "TELEMETRY", client.clone()).await,
            settings,
            client,
            logs,
        })
    }
}

pub mod documentation;
