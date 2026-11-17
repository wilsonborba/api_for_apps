//! Central, app-linked waitlist. A target is a plan, a feature or a stated
//! communication interest of one registered application. Repeated sign-ups
//! are no-ops and responses never reveal whether an email is already listed.
pub use crate::domain::models::waitlist::Failure;
use crate::domain::models::waitlist::{
    DEFAULT_LIMIT, Entry, Filter, Join, MAX_LIMIT, MAX_OFFSET, NewEntry, STATUSES, StatusUpdate,
    TARGET_TYPES,
};
use crate::{dal::local::waitlist as storage, domain::State};
use anyhow::{Result, bail};

impl Failure {
    pub fn code(self) -> &'static str {
        match self {
            Self::Invalid => "INVALID_WAITLIST_DATA",
            Self::AppNotFound => "WAITLIST_APP_NOT_FOUND",
            Self::TargetNotFound => "WAITLIST_TARGET_NOT_FOUND",
            Self::NotFound => "WAITLIST_ENTRY_NOT_FOUND",
            Self::RateLimited => "WAITLIST_RATE_LIMITED",
        }
    }
    pub fn status(self) -> u16 {
        match self {
            Self::Invalid => 400,
            Self::RateLimited => 429,
            _ => 404,
        }
    }
    pub fn message(self) -> &'static str {
        match self {
            Self::Invalid => "Invalid waitlist data.",
            Self::AppNotFound => "Application is not registered or not active.",
            Self::TargetNotFound => "Waitlist target is not available for this application.",
            Self::NotFound => "Waitlist entry not found.",
            Self::RateLimited => "Request could not be completed. Please try again later.",
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
static EMAIL: std::sync::LazyLock<regex::Regex> =
    std::sync::LazyLock::new(|| regex::Regex::new(r"^[^@\s]+@[^@\s]+\.[^@\s]+$").unwrap());
/// Normalized email, or `None` when it is not a plausible address.
pub fn email(value: &str) -> Option<String> {
    let email = value.trim().to_lowercase();
    ((3..=320).contains(&email.len()) && EMAIL.is_match(&email)).then_some(email)
}
/// Validated public request with its normalized email. Done before rate limiting.
pub fn validate(input: Join) -> Result<Join> {
    let email = email(&input.email).ok_or(Failure::Invalid)?;
    if !code(&input.app_id)
        || !TARGET_TYPES.contains(&input.target_type.as_str())
        || !code(&input.target)
    {
        bail!(Failure::Invalid)
    }
    Ok(Join { email, ..input })
}
/// Records a validated request. `user` is the session user whose own email
/// matches the request; other sessions never link an entry.
pub async fn join(s: &State, input: Join, user: Option<String>) -> Result<()> {
    if storage::app_active(&s.db, &input.app_id).await? != Some(true) {
        bail!(Failure::AppNotFound)
    }
    let (mut plan_id, mut feature_id, mut interest) = (None, None, None);
    match input.target_type.as_str() {
        "interest" => interest = Some(input.target),
        kind => {
            let id = storage::target_id(&s.db, kind, &input.app_id, &input.target)
                .await?
                .ok_or(Failure::TargetNotFound)?;
            if kind == "plan" {
                plan_id = Some(id)
            } else {
                feature_id = Some(id)
            }
        }
    }
    storage::join(
        &s.db,
        &NewEntry {
            app_id: input.app_id,
            target_type: input.target_type,
            plan_id,
            feature_id,
            interest,
            email: input.email,
            user_id: user,
        },
    )
    .await
}
pub async fn entries(s: &State, q: Filter) -> Result<Vec<Entry>> {
    let limit = q.limit.unwrap_or(DEFAULT_LIMIT);
    let offset = q.offset.unwrap_or(0);
    if !(1..=MAX_LIMIT).contains(&limit)
        || !(0..=MAX_OFFSET).contains(&offset)
        || q.app_id.as_deref().is_some_and(|v| !code(v))
        || q.target.as_deref().is_some_and(|v| !code(v))
        || q.target_type
            .as_deref()
            .is_some_and(|v| !TARGET_TYPES.contains(&v))
        || q.status.as_deref().is_some_and(|v| !STATUSES.contains(&v))
    {
        bail!(Failure::Invalid)
    }
    storage::entries(&s.db, &q, limit, offset).await
}
pub async fn update(s: &State, id: &str, input: StatusUpdate) -> Result<Entry> {
    if uuid::Uuid::parse_str(id).is_err() || !STATUSES.contains(&input.status.as_str()) {
        bail!(Failure::Invalid)
    }
    if !storage::set_status(&s.db, id, &input.status).await? {
        bail!(Failure::NotFound)
    }
    storage::entry(&s.db, id)
        .await?
        .ok_or_else(|| Failure::NotFound.into())
}
