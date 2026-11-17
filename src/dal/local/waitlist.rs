//! Typed SQL over the central waitlist. Every value is bound; no cached rows.
use super::database::{Database, all, execute, one};
use crate::domain::models::waitlist::{Entry, Filter, NewEntry};
use anyhow::Result;
use chrono::Utc;

const ENTRY: &str = "SELECT w.id,w.app_id,w.target_type,COALESCE(p.code,f.code,w.interest) AS target,w.plan_id,w.feature_id,w.interest,w.email,w.user_id,w.status,w.created_at,w.updated_at FROM app_waitlist_entries w LEFT JOIN app_plans p ON p.id=w.plan_id LEFT JOIN app_features f ON f.id=w.feature_id";

pub async fn app_active(db: &Database, app: &str) -> Result<Option<bool>> {
    let row: Option<(bool,)> = one!(
        db,
        (bool,),
        "SELECT is_active FROM defaultdb_app WHERE id=$1",
        app
    );
    Ok(row.map(|r| r.0))
}
/// Plan or feature id for an app-scoped code. Inactive future rows can be targets.
pub async fn target_id(db: &Database, kind: &str, app: &str, code: &str) -> Result<Option<String>> {
    let sql = if kind == "plan" {
        "SELECT id FROM app_plans WHERE app_id=$1 AND code=$2"
    } else {
        "SELECT id FROM app_features WHERE app_id=$1 AND code=$2"
    };
    let row: Option<(String,)> = one!(db, (String,), sql, app, code);
    Ok(row.map(|r| r.0))
}
/// Inserts once per app, target and email. Repeats change nothing except
/// linking an unlinked entry to the verified session user.
pub async fn join(db: &Database, row: &NewEntry) -> Result<()> {
    let now = Utc::now();
    execute!(
        db,
        "INSERT INTO app_waitlist_entries(id,app_id,target_type,plan_id,feature_id,interest,email,user_id,status,created_at,updated_at) VALUES($1,$2,$3,$4,$5,$6,$7,(SELECT uuid_id FROM defaultdb_user WHERE uuid_id=$8),'pending',$9,$9) ON CONFLICT DO NOTHING",
        uuid::Uuid::new_v4().to_string(),
        &row.app_id,
        &row.target_type,
        &row.plan_id,
        &row.feature_id,
        &row.interest,
        &row.email,
        &row.user_id,
        now
    );
    if row.user_id.is_some() {
        execute!(
            db,
            "UPDATE app_waitlist_entries SET user_id=$1,updated_at=$2 WHERE user_id IS NULL AND app_id=$3 AND target_type=$4 AND email=$5 AND COALESCE(plan_id,feature_id,interest)=$6 AND EXISTS (SELECT 1 FROM defaultdb_user WHERE uuid_id=$1)",
            &row.user_id,
            now,
            &row.app_id,
            &row.target_type,
            &row.email,
            row.plan_id
                .as_ref()
                .or(row.feature_id.as_ref())
                .or(row.interest.as_ref())
        );
    }
    Ok(())
}
pub async fn entries(db: &Database, q: &Filter, limit: i64, offset: i64) -> Result<Vec<Entry>> {
    Ok(all!(
        db,
        Entry,
        &format!(
            "{ENTRY} WHERE (CAST($1 AS TEXT) IS NULL OR w.app_id=$1) AND (CAST($2 AS TEXT) IS NULL OR w.target_type=$2) AND (CAST($3 AS TEXT) IS NULL OR COALESCE(p.code,f.code,w.interest)=$3) AND (CAST($4 AS TEXT) IS NULL OR w.status=$4) ORDER BY w.created_at DESC,w.id LIMIT $5 OFFSET $6"
        ),
        &q.app_id,
        &q.target_type,
        &q.target,
        &q.status,
        limit,
        offset
    ))
}
pub async fn entry(db: &Database, id: &str) -> Result<Option<Entry>> {
    Ok(one!(db, Entry, &format!("{ENTRY} WHERE w.id=$1"), id))
}
pub async fn set_status(db: &Database, id: &str, status: &str) -> Result<bool> {
    Ok(execute!(
        db,
        "UPDATE app_waitlist_entries SET status=$1,updated_at=$2 WHERE id=$3",
        status,
        Utc::now(),
        id
    ) > 0)
}
