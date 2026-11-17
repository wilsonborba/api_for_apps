//! Central plan catalog rows and typed request/response structures.
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

#[derive(Debug, Clone, Deserialize, Serialize, FromRow)]
pub struct Plan {
    pub id: String,
    pub app_id: String,
    pub code: String,
    pub name: String,
    pub description: String,
    pub is_active: bool,
}
#[derive(Debug, Clone, Deserialize, Serialize, FromRow)]
pub struct Feature {
    pub id: String,
    pub app_id: String,
    pub code: String,
    pub name: String,
    pub description: String,
    pub is_active: bool,
}
#[derive(Serialize)]
pub struct PlanView {
    #[serde(flatten)]
    pub plan: Plan,
    pub features: Vec<Feature>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Create {
    pub app_id: String,
    pub code: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub is_active: bool,
}
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Update {
    pub name: Option<String>,
    pub description: Option<String>,
    pub is_active: Option<bool>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Membership {
    pub plan_id: String,
    pub feature_id: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AppQuery {
    pub app_id: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    Invalid,
    NotFound,
    AppNotFound,
    Conflict,
    CrossApp,
    FreeOnly,
}
