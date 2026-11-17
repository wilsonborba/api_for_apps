//! Central, app-linked plan data. Free is the only active plan; this module
//! creates no subscriptions, payment state, quotas or application entitlements.
pub use crate::domain::models::plans::Failure;
use crate::domain::models::plans::{Create, Feature, Membership, Plan, PlanView, Update};
use crate::{dal::local::plans as storage, domain::State};
use anyhow::{Result, bail};

impl Failure {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "INVALID_PLAN_DATA",
            Self::NotFound => "PLAN_RECORD_NOT_FOUND",
            Self::AppNotFound => "PLAN_APP_NOT_FOUND",
            Self::Conflict => "PLAN_RECORD_CONFLICT",
            Self::CrossApp => "PLAN_FEATURE_APP_MISMATCH",
            Self::FreeOnly => "ONLY_FREE_PLAN_ACTIVE",
        }
    }
    pub fn status(self) -> u16 {
        match self {
            Self::NotFound | Self::AppNotFound => 404,
            Self::Conflict => 409,
            _ => 400,
        }
    }
    pub fn message(self) -> &'static str {
        match self {
            Self::Invalid => "Invalid plan or feature data.",
            Self::NotFound => "Plan, feature or membership not found.",
            Self::AppNotFound => "Application is not registered.",
            Self::Conflict => "This plan or feature conflicts with existing data.",
            Self::CrossApp => "Plan and feature must belong to the same application.",
            Self::FreeOnly => "Free is the only plan that can be active.",
        }
    }
}
impl std::fmt::Display for Failure {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.message())
    }
}
impl std::error::Error for Failure {}
fn code(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.as_bytes()[0].is_ascii_lowercase()
        && value
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
}
pub fn app_id(value: &str) -> Result<()> {
    if !code(value) {
        bail!(Failure::Invalid)
    }
    Ok(())
}
fn id(value: &str) -> Result<()> {
    if uuid::Uuid::parse_str(value).is_err() {
        bail!(Failure::Invalid)
    }
    Ok(())
}
fn content(name: &str, description: &str) -> Result<()> {
    if name.trim().is_empty() || name.chars().count() > 160 || description.chars().count() > 2048 {
        bail!(Failure::Invalid)
    }
    Ok(())
}
fn database_error(error: anyhow::Error) -> anyhow::Error {
    if let Some(sqlx::Error::Database(db)) = error.downcast_ref::<sqlx::Error>()
        && (db.is_unique_violation() || db.is_foreign_key_violation() || db.is_check_violation())
    {
        return Failure::Conflict.into();
    }
    error
}
async fn registered(s: &State, app: &str) -> Result<()> {
    app_id(app)?;
    if !storage::app_exists(&s.db, app).await? {
        bail!(Failure::AppNotFound)
    }
    Ok(())
}
pub async fn plans(s: &State, app: &str, public: bool) -> Result<Vec<PlanView>> {
    app_id(app)?;
    let mut result = Vec::new();
    for plan in storage::plans(&s.db, app, public).await? {
        let features = storage::features_for_plan(&s.db, &plan.id, public).await?;
        result.push(PlanView { plan, features });
    }
    Ok(result)
}
pub async fn features(s: &State, app: &str) -> Result<Vec<Feature>> {
    app_id(app)?;
    storage::features(&s.db, app).await
}
pub async fn create_plan(s: &State, input: Create) -> Result<Plan> {
    registered(s, &input.app_id).await?;
    if !code(&input.code) {
        bail!(Failure::Invalid)
    }
    content(&input.name, &input.description)?;
    if input.is_active && input.code != "free" {
        bail!(Failure::FreeOnly)
    }
    let row = Plan {
        id: uuid::Uuid::new_v4().to_string(),
        app_id: input.app_id,
        code: input.code,
        name: input.name.trim().into(),
        description: input.description,
        is_active: input.is_active,
    };
    storage::insert_plan(&s.db, &row)
        .await
        .map_err(database_error)?;
    Ok(row)
}
pub async fn create_feature(s: &State, input: Create) -> Result<Feature> {
    registered(s, &input.app_id).await?;
    if !code(&input.code) {
        bail!(Failure::Invalid)
    }
    content(&input.name, &input.description)?;
    let row = Feature {
        id: uuid::Uuid::new_v4().to_string(),
        app_id: input.app_id,
        code: input.code,
        name: input.name.trim().into(),
        description: input.description,
        is_active: input.is_active,
    };
    storage::insert_feature(&s.db, &row)
        .await
        .map_err(database_error)?;
    Ok(row)
}
pub async fn update_plan(s: &State, value: &str, input: Update) -> Result<Plan> {
    id(value)?;
    if input.name.is_none() && input.description.is_none() && input.is_active.is_none() {
        bail!(Failure::Invalid)
    }
    let mut row = storage::plan(&s.db, value)
        .await?
        .ok_or(Failure::NotFound)?;
    row.name = input.name.unwrap_or(row.name).trim().into();
    row.description = input.description.unwrap_or(row.description);
    row.is_active = input.is_active.unwrap_or(row.is_active);
    content(&row.name, &row.description)?;
    if row.is_active && row.code != "free" {
        bail!(Failure::FreeOnly)
    }
    if !storage::update_plan(&s.db, &row)
        .await
        .map_err(database_error)?
    {
        bail!(Failure::NotFound)
    }
    Ok(row)
}
pub async fn update_feature(s: &State, value: &str, input: Update) -> Result<Feature> {
    id(value)?;
    if input.name.is_none() && input.description.is_none() && input.is_active.is_none() {
        bail!(Failure::Invalid)
    }
    let mut row = storage::feature(&s.db, value)
        .await?
        .ok_or(Failure::NotFound)?;
    row.name = input.name.unwrap_or(row.name).trim().into();
    row.description = input.description.unwrap_or(row.description);
    row.is_active = input.is_active.unwrap_or(row.is_active);
    content(&row.name, &row.description)?;
    if !storage::update_feature(&s.db, &row)
        .await
        .map_err(database_error)?
    {
        bail!(Failure::NotFound)
    }
    Ok(row)
}
pub async fn delete_plan(s: &State, value: &str) -> Result<()> {
    id(value)?;
    if !storage::delete_plan(&s.db, value)
        .await
        .map_err(database_error)?
    {
        bail!(Failure::NotFound)
    }
    Ok(())
}
pub async fn delete_feature(s: &State, value: &str) -> Result<()> {
    id(value)?;
    if !storage::delete_feature(&s.db, value)
        .await
        .map_err(database_error)?
    {
        bail!(Failure::NotFound)
    }
    Ok(())
}
pub async fn attach(s: &State, input: &Membership) -> Result<()> {
    id(&input.plan_id)?;
    id(&input.feature_id)?;
    let plan = storage::plan(&s.db, &input.plan_id)
        .await?
        .ok_or(Failure::NotFound)?;
    let feature = storage::feature(&s.db, &input.feature_id)
        .await?
        .ok_or(Failure::NotFound)?;
    if plan.app_id != feature.app_id {
        bail!(Failure::CrossApp)
    }
    storage::attach(&s.db, &plan.app_id, &input.plan_id, &input.feature_id)
        .await
        .map_err(database_error)
}
pub async fn detach(s: &State, plan: &str, feature: &str) -> Result<()> {
    id(plan)?;
    id(feature)?;
    if !storage::detach(&s.db, plan, feature).await? {
        bail!(Failure::NotFound)
    }
    Ok(())
}
