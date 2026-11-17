//! Typed SQL operations over normalized central plan rows. No cached plan data.
use super::database::Database;
use crate::domain::models::plans::{Feature, Plan};
use anyhow::Result;

macro_rules! all {
    ($db:expr,$kind:ty,$sql:expr $(,$value:expr)* $(,)?) => {{
        match $db {
            Database::Pg(pool) => sqlx::query_as::<_, $kind>($sql)$(.bind($value))*.fetch_all(pool).await?,
            Database::Sqlite(pool) => sqlx::query_as::<_, $kind>($sql)$(.bind($value))*.fetch_all(pool).await?,
        }
    }};
}
macro_rules! one {
    ($db:expr,$kind:ty,$sql:expr $(,$value:expr)* $(,)?) => {{
        match $db {
            Database::Pg(pool) => sqlx::query_as::<_, $kind>($sql)$(.bind($value))*.fetch_optional(pool).await?,
            Database::Sqlite(pool) => sqlx::query_as::<_, $kind>($sql)$(.bind($value))*.fetch_optional(pool).await?,
        }
    }};
}
macro_rules! execute {
    ($db:expr,$sql:expr $(,$value:expr)* $(,)?) => {{
        match $db {
            Database::Pg(pool) => sqlx::query($sql)$(.bind($value))*.execute(pool).await?.rows_affected(),
            Database::Sqlite(pool) => sqlx::query($sql)$(.bind($value))*.execute(pool).await?.rows_affected(),
        }
    }};
}
const PLAN_COLUMNS: &str = "id,app_id,code,name,description,is_active";
// Query text is static. All identifiers and values from API calls are bound.
pub async fn app_exists(db: &Database, app: &str) -> Result<bool> {
    let row: Option<(String,)> = one!(
        db,
        (String,),
        "SELECT id FROM defaultdb_app WHERE id=$1",
        app
    );
    Ok(row.is_some())
}
pub async fn plans(db: &Database, app: &str, active_only: bool) -> Result<Vec<Plan>> {
    Ok(all!(
        db,
        Plan,
        "SELECT p.id,p.app_id,p.code,p.name,p.description,p.is_active FROM app_plans p JOIN defaultdb_app a ON a.id=p.app_id WHERE p.app_id=$1 AND (NOT $2 OR (p.is_active AND a.is_active)) ORDER BY p.code,p.id",
        app,
        active_only
    ))
}
pub async fn features(db: &Database, app: &str) -> Result<Vec<Feature>> {
    Ok(all!(
        db,
        Feature,
        "SELECT id,app_id,code,name,description,is_active FROM app_features WHERE app_id=$1 ORDER BY code,id",
        app
    ))
}
pub async fn features_for_plan(
    db: &Database,
    plan: &str,
    active_only: bool,
) -> Result<Vec<Feature>> {
    Ok(all!(
        db,
        Feature,
        "SELECT f.id,f.app_id,f.code,f.name,f.description,f.is_active FROM app_features f JOIN plan_features pf ON pf.feature_id=f.id AND pf.app_id=f.app_id WHERE pf.plan_id=$1 AND (NOT $2 OR f.is_active) ORDER BY f.code,f.id",
        plan,
        active_only
    ))
}
pub async fn plan(db: &Database, id: &str) -> Result<Option<Plan>> {
    Ok(one!(
        db,
        Plan,
        &format!("SELECT {PLAN_COLUMNS} FROM app_plans WHERE id=$1"),
        id
    ))
}
pub async fn feature(db: &Database, id: &str) -> Result<Option<Feature>> {
    Ok(one!(
        db,
        Feature,
        "SELECT id,app_id,code,name,description,is_active FROM app_features WHERE id=$1",
        id
    ))
}
pub async fn insert_plan(db: &Database, row: &Plan) -> Result<()> {
    execute!(
        db,
        "INSERT INTO app_plans(id,app_id,code,name,description,is_active) VALUES($1,$2,$3,$4,$5,$6)",
        &row.id,
        &row.app_id,
        &row.code,
        &row.name,
        &row.description,
        row.is_active
    );
    Ok(())
}
pub async fn insert_feature(db: &Database, row: &Feature) -> Result<()> {
    execute!(
        db,
        "INSERT INTO app_features(id,app_id,code,name,description,is_active) VALUES($1,$2,$3,$4,$5,$6)",
        &row.id,
        &row.app_id,
        &row.code,
        &row.name,
        &row.description,
        row.is_active
    );
    Ok(())
}
pub async fn update_plan(db: &Database, row: &Plan) -> Result<bool> {
    Ok(execute!(
        db,
        "UPDATE app_plans SET name=$1,description=$2,is_active=$3 WHERE id=$4",
        &row.name,
        &row.description,
        row.is_active,
        &row.id
    ) > 0)
}
pub async fn update_feature(db: &Database, row: &Feature) -> Result<bool> {
    Ok(execute!(
        db,
        "UPDATE app_features SET name=$1,description=$2,is_active=$3 WHERE id=$4",
        &row.name,
        &row.description,
        row.is_active,
        &row.id
    ) > 0)
}
pub async fn delete_plan(db: &Database, id: &str) -> Result<bool> {
    Ok(execute!(db, "DELETE FROM app_plans WHERE id=$1", id) > 0)
}
pub async fn delete_feature(db: &Database, id: &str) -> Result<bool> {
    Ok(execute!(db, "DELETE FROM app_features WHERE id=$1", id) > 0)
}
pub async fn attach(db: &Database, app: &str, plan: &str, feature: &str) -> Result<()> {
    execute!(
        db,
        "INSERT INTO plan_features(app_id,plan_id,feature_id) VALUES($1,$2,$3)",
        app,
        plan,
        feature
    );
    Ok(())
}
pub async fn detach(db: &Database, plan: &str, feature: &str) -> Result<bool> {
    Ok(execute!(
        db,
        "DELETE FROM plan_features WHERE plan_id=$1 AND feature_id=$2",
        plan,
        feature
    ) > 0)
}
