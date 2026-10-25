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
