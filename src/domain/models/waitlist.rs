//! Central waitlist rows and typed request structures. Scalar columns only.
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;

pub const TARGET_TYPES: [&str; 3] = ["plan", "feature", "interest"];
pub const STATUSES: [&str; 4] = ["pending", "contacted", "converted", "declined"];
pub const DEFAULT_LIMIT: i64 = 50;
pub const MAX_LIMIT: i64 = 100;
pub const MAX_OFFSET: i64 = 10_000;

/// One stored entry. `target` is the plan code, feature code or interest code.
#[derive(Debug, Clone, Serialize, FromRow)]
pub struct Entry {
    pub id: String,
    pub app_id: String,
    pub target_type: String,
    pub target: String,
    pub plan_id: Option<String>,
    pub feature_id: Option<String>,
    pub interest: Option<String>,
    pub email: String,
    pub user_id: Option<String>,
    pub status: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}
/// Resolved target columns for one new entry.
pub struct NewEntry {
    pub app_id: String,
    pub target_type: String,
    pub plan_id: Option<String>,
    pub feature_id: Option<String>,
    pub interest: Option<String>,
    pub email: String,
    pub user_id: Option<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Join {
    pub app_id: String,
    pub target_type: String,
    pub target: String,
    pub email: String,
}
#[derive(Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Filter {
    pub app_id: Option<String>,
    pub target_type: Option<String>,
    pub target: Option<String>,
    pub status: Option<String>,
    pub limit: Option<i64>,
    pub offset: Option<i64>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StatusUpdate {
    pub status: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Failure {
    Invalid,
    AppNotFound,
    TargetNotFound,
    NotFound,
    RateLimited,
}
