use super::*;
use axum::{
    body::{Body, to_bytes},
    extract::ConnectInfo,
    http::{Request, StatusCode},
};
use serde_json::{Value, json};
use std::{collections::HashMap, sync::Arc};
use tower::ServiceExt;
async fn state() -> domain::State {
    let values: HashMap<String, String> = [
        ("REDIS_URL", "memory://"),
        ("API_KEY_SECRET", "test-admin"),
        (
            "FERNET_KEY_SECRET",
            "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        ),
    ]
    .into_iter()
    .map(|(k, v)| (k.into(), v.into()))
    .collect();
    let settings = core::settings::Settings {
        values: Arc::new(values),
        defaults: Arc::new(serde_json::from_str(include_str!("core/defaults.json")).unwrap()),
    };
    let client = reqwest::Client::new();
    let db = sqlx::SqlitePool::connect("sqlite::memory:").await.unwrap();
    sqlx::query("CREATE TABLE defaultdb_user (id INTEGER PRIMARY KEY, uuid_id TEXT, email TEXT, access_level INTEGER, is_active INTEGER)").execute(&db).await.unwrap();
    sqlx::query("CREATE TABLE defaultdb_support_ticket(id TEXT PRIMARY KEY,user_id TEXT,source_app TEXT,status TEXT,created_at TEXT,updated_at TEXT)").execute(&db).await.unwrap();
    let (logs, _) = tokio::sync::broadcast::channel(256);
    domain::State {
        cache: dal::cache::Cache::new("memory://", "").await.unwrap(),
        db: dal::database::Database::Sqlite(db),
        support: dal::documents::Documents::new(&settings, "SUPPORT", client.clone()).await,
        telemetry: dal::documents::Documents::new(&settings, "TELEMETRY", client.clone()).await,
        settings,
        client,
        logs,
    }
}
async fn call(
    s: domain::State,
    method: &str,
    path: &str,
    body: Value,
    headers: &[(&str, &str)],
) -> (StatusCode, Value) {
    let mut req = Request::builder().method(method).uri(path);
    for (k, v) in headers {
        req = req.header(*k, *v)
    }
    let mut req = req
        .body(Body::from(serde_json::to_vec(&body).unwrap()))
        .unwrap();
    req.extensions_mut().insert(ConnectInfo(
        "127.0.0.1:5000".parse::<std::net::SocketAddr>().unwrap(),
    ));
    let r = presentation::router(s).oneshot(req).await.unwrap();
    let status = r.status();
    let b = to_bytes(r.into_body(), 4 * 1024 * 1024).await.unwrap();
    (status, serde_json::from_slice(&b).unwrap_or(Value::Null))
}
#[tokio::test]
async fn one_use_cache_and_ttl() {
    let c = dal::cache::Cache::new("memory://", "").await.unwrap();
    assert!(c.set("k", json!({"app":"reports"}), 1, true).await.unwrap());
    assert!(!c.set("k", json!(0), 1, true).await.unwrap());
    assert!(c.get("k", true).await.unwrap().is_some());
    assert!(c.get("k", true).await.unwrap().is_none());
    assert_eq!(c.increment("n", 1).await.unwrap(), 1);
    assert_eq!(c.increment("n", 1).await.unwrap(), 2);
    tokio::time::sleep(std::time::Duration::from_millis(1050)).await;
    assert_eq!(c.increment("n", 1).await.unwrap(), 1);
}
#[tokio::test]
async fn admin_logs_deny_guests_and_users() {
    let s = state().await;
    assert_eq!(
        call(s.clone(), "GET", "/apps/api/v1/logs/stream", json!({}), &[])
            .await
            .0,
        403
    );
    s.cache
        .set(
            "exchange_auth_app:user",
            json!({"user_uuid_id":"u","access_level":3,"csrf_token":"c"}),
            60,
            false,
        )
        .await
        .unwrap();
    assert_eq!(
        call(
            s,
            "GET",
            "/apps/api/v1/logs/stream",
            json!({}),
            &[("cookie", "sid=user")]
        )
        .await
        .0,
        403
    );
}
#[tokio::test]
async fn csrf_and_admin_boundaries() {
    let s = state().await;
    s.cache
        .set(
            "exchange_auth_app:admin",
            json!({"user_uuid_id":"a","access_level":1,"csrf_token":"c"}),
            60,
            false,
        )
        .await
        .unwrap();
    let mut h = axum::http::HeaderMap::new();
    h.insert("cookie", "sid=admin; csrf=c".parse().unwrap());
    assert!(domain::auth::verify(&s, &h, "POST", true).await.is_err());
    h.insert("x-csrf-token", "c".parse().unwrap());
    assert!(domain::auth::verify(&s, &h, "POST", true).await.is_ok());
    s.cache.delete("exchange_auth_app:admin").await.unwrap();
    assert!(domain::auth::verify(&s, &h, "GET", true).await.is_err());
}
#[tokio::test]
async fn fernet_and_single_use_artifact() {
    let s = state().await;
    let p = json!({"jti":"j","app":"reports","uuid_id":"u","email":"u@example.test","access_level":3,"is_active":true,"id":1,"provider_user_id":"sub","provider":"supabase","exp":domain::auth::now()+30});
    let f = fernet::Fernet::new(&s.settings.get("FERNET_KEY_SECRET")).unwrap();
    let t = f.encrypt(&serde_json::to_vec(&p).unwrap());
    s.cache
        .set("exchange_artifact:j", json!({"app":"reports"}), 30, true)
        .await
        .unwrap();
    assert!(domain::auth::redeem(&s, &t, "cortex").await.is_err());
    let u = domain::auth::redeem(&s, &t, "reports").await.unwrap();
    assert_eq!(u["user_uuid_id"], "u");
    assert!(domain::auth::redeem(&s, &t, "reports").await.is_err());
    let encoded = rmp_serde::to_vec_named(&u).unwrap();
    assert_eq!(rmp_serde::from_slice::<Value>(&encoded).unwrap(), u);
}
#[tokio::test]
async fn ticket_ownership_and_admin_thread() {
    let s = state().await;
    let a = json!({"user_uuid_id":"a","access_level":3});
    let b = json!({"user_uuid_id":"b","access_level":3});
    let admin = json!({"user_uuid_id":"root","access_level":1});
    let t = domain::support::create(&s, &a, &json!({"source_app":"reports","body":"Hello"}))
        .await
        .unwrap();
    let id = t["id"].as_str().unwrap();
    assert!(domain::support::get(&s, id, &b).await.is_err());
    let m = domain::support::reply(&s, id, &admin, &json!({"body":"Reply"}))
        .await
        .unwrap();
    assert_eq!(m["sender"], "admin");
    assert_eq!(
        domain::support::get(&s, id, &a).await.unwrap()["messages"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    assert_eq!(
        domain::support::mark(&s, id, None, &admin).await.unwrap()["count"],
        2
    );
}
#[tokio::test]
async fn docs_only_and_public_spec() {
    let s = state().await;
    assert_eq!(
        call(s.clone(), "GET", "/scalar", json!({}), &[]).await.0,
        404
    );
    let (status, v) = call(s, "GET", "/openapi.json", json!({}), &[]).await;
    assert_eq!(status, 200);
    assert!(v["paths"].as_object().unwrap().len() > 100);
}

#[test]
fn central_runtime_discovers_route_add_change_remove_without_service_openapi() {
    let workspace =
        std::env::temp_dir().join(format!("asodya-source-test-{}", uuid::Uuid::new_v4()));
    let repo = workspace.join("certifications_api");
    std::fs::create_dir_all(&repo).unwrap();
    let source = repo.join("routes.py");
    let base = json!({"paths":{}});
    std::fs::write(
        &source,
        "r=APIRouter(prefix='/fixture')\n@r.get('/one')\nasync def one(): pass\n",
    )
    .unwrap();
    let one = domain::documentation::refresh(base, &workspace);
    assert!(one["paths"]["/apps/certifications/v1/fixture/one"]["get"].is_object());
    std::fs::write(
        &source,
        "r=APIRouter(prefix='/fixture')\n@r.post('/two')\nasync def two(): pass\n",
    )
    .unwrap();
    let two = domain::documentation::refresh(one, &workspace);
    assert!(two["paths"]["/apps/certifications/v1/fixture/one"].is_null());
    assert!(two["paths"]["/apps/certifications/v1/fixture/two"]["post"].is_object());
    std::fs::write(&source, "r=APIRouter(prefix='/fixture')\n").unwrap();
    let removed = domain::documentation::refresh(two, &workspace);
    assert!(removed["paths"]["/apps/certifications/v1/fixture/two"].is_null());
    std::fs::remove_dir_all(workspace).unwrap();
}
