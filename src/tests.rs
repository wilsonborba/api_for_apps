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
    sqlx::query("CREATE TABLE defaultdb_user (id INTEGER PRIMARY KEY, uuid_id TEXT, email TEXT, access_level INTEGER, is_active INTEGER, username TEXT, first_name TEXT, last_name TEXT, password TEXT, last_login TEXT, date_joined TEXT, phone_number TEXT, supabase_user_id TEXT)").execute(&db).await.unwrap();
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
    std::fs::write(&source,"r=APIRouter(prefix='/fixture')\n@r.post('/two')\nasync def two(): return {'changed':True}\n").unwrap();
    let changed = domain::documentation::refresh(two.clone(), &workspace);
    assert_eq!(
        changed["paths"]["/apps/certifications/v1/fixture/two"]["post"]["x-source-outdated"],
        true
    );
    std::fs::write(&source, "r=APIRouter(prefix='/fixture')\n").unwrap();
    let removed = domain::documentation::refresh(two, &workspace);
    assert!(removed["paths"]["/apps/certifications/v1/fixture/two"].is_null());
    std::fs::remove_dir_all(workspace).unwrap();
}

#[tokio::test]
async fn method_and_typed_body_contracts() {
    let s = state().await;
    assert_eq!(
        call(s.clone(), "GET", "/user/sync/v1/log-in", json!({}), &[])
            .await
            .0,
        405
    );
    let (status, v) = call(
        s.clone(),
        "POST",
        "/user/sync/v1/password-recovery",
        json!({}),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, 422);
    assert_eq!(v["detail"][0]["type"], "missing");
    assert_eq!(v["detail"][0]["loc"], json!(["body", "email"]));
    assert_eq!(
        call(
            s,
            "POST",
            "/user/sync/v1/password-recovery",
            json!({"email":"u@example.test"}),
            &[("content-type", "text/plain")]
        )
        .await
        .0,
        422
    );
}

#[tokio::test]
async fn support_auth_precedes_body_validation() {
    let s = state().await;
    let (status, _) = call(
        s.clone(),
        "POST",
        "/apps/support/v1/tickets",
        json!({}),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, 403);
    s.cache
        .set(
            "exchange_auth_app:user",
            json!({"user_uuid_id":"u","access_level":3,"csrf_token":"c"}),
            60,
            false,
        )
        .await
        .unwrap();
    let (status, v) = call(
        s,
        "POST",
        "/apps/support/v1/tickets",
        json!({}),
        &[
            ("content-type", "application/json"),
            ("cookie", "sid=user; csrf=c"),
            ("x-csrf-token", "c"),
        ],
    )
    .await;
    assert_eq!(status, 422);
    assert!(v["detail"].is_array());
}

#[test]
fn runtime_settings_reject_missing_credentials() {
    let settings = core::settings::Settings {
        values: Arc::new(HashMap::new()),
        defaults: Arc::new(serde_json::from_str(include_str!("core/defaults.json")).unwrap()),
    };
    assert!(
        settings
            .validate_runtime()
            .unwrap_err()
            .to_string()
            .contains("API_KEY_SECRET")
    );
}

#[tokio::test]
async fn hello_only_selects_available_kjv_verses() {
    for _ in 0..1024 {
        let r = presentation::docs::hello();
        assert_eq!(r.status(), StatusCode::OK);
        let body: Value =
            serde_json::from_slice(&to_bytes(r.into_body(), 65536).await.unwrap()).unwrap();
        assert!(!body["data"].is_null());
    }
}

#[tokio::test]
async fn oauth_callback_accepts_rest_tokens_and_rejects_missing_sessions() {
    use axum::routing::{get, post};
    let provider = axum::Router::new()
        .route("/auth/v1/token", post(|axum::Json(body): axum::Json<Value>| async move {
            axum::Json(match body["auth_code"].as_str().unwrap() {
                "root" => json!({"access_token":"root-access", "token_type":"bearer"}),
                "nested" => json!({"session":{"access_token":"nested-access"}}),
                "empty" => json!({"access_token":"   "}),
                _ => json!({}),
            })
        }))
        .route("/auth/v1/user", get(|h: axum::http::HeaderMap| async move {
            assert!(matches!(h.get("authorization").unwrap().to_str().unwrap(), "Bearer root-access" | "Bearer nested-access"));
            axum::Json(json!({"id":"provider-fixture", "email":"oauth@example.test", "user_metadata":{}}))
        }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move { axum::serve(listener, provider).await.unwrap() });
    let mut s = state().await;
    let mut values = (*s.settings.values).clone();
    values.insert("SUPABASE_URL".into(), format!("http://{address}"));
    values.insert("SUPABASE_SECRET_KEY".into(), "fixture".into());
    s.settings.values = Arc::new(values);
    for (code, expected) in [
        ("root", 200),
        ("nested", 200),
        ("empty", 400),
        ("missing", 400),
    ] {
        let key = format!("{}:{code}", s.settings.get("OAUTH_STATE_PREFIX"));
        s.cache
            .set(
                &key,
                json!({"app":"reports","code_verifier":"fixture-verifier"}),
                60,
                false,
            )
            .await
            .unwrap();
        let body = json!({"code":code,"state":code});
        let (status, response) = call(
            s.clone(),
            "POST",
            "/user/sync/v1/oauth/callback",
            body.clone(),
            &[],
        )
        .await;
        assert_eq!(status.as_u16(), expected, "{code}: {response}");
        if expected == 200 {
            let artifact = response["data"].as_str().unwrap();
            let payload = fernet::Fernet::new(&s.settings.get("FERNET_KEY_SECRET"))
                .unwrap()
                .decrypt(artifact)
                .unwrap();
            let payload: Value = serde_json::from_slice(&payload).unwrap();
            assert_eq!(payload["app"], "reports");
            assert_eq!(
                call(s.clone(), "POST", "/user/sync/v1/oauth/callback", body, &[])
                    .await
                    .0,
                400
            );
        }
    }
    task.abort();
}

#[tokio::test]
async fn documentation_assets_support_gzip_and_identity() {
    let h = axum::http::HeaderMap::new();
    let raw = presentation::docs::asset("/docs/assets/scalar-1.76.0.js", &h);
    assert_eq!(raw.status(), StatusCode::OK);
    assert!(!raw.headers().contains_key("content-encoding"));
    let raw = to_bytes(raw.into_body(), 8 * 1024 * 1024).await.unwrap();
    let mut h = h;
    h.insert("accept-encoding", "br, gzip".parse().unwrap());
    let compressed = presentation::docs::asset("/docs/assets/scalar-1.76.0.js", &h);
    assert_eq!(compressed.headers()["content-encoding"], "gzip");
    let compressed = to_bytes(compressed.into_body(), 8 * 1024 * 1024)
        .await
        .unwrap();
    use std::io::Read;
    let mut decoded = Vec::new();
    flate2::read::GzDecoder::new(compressed.as_ref())
        .read_to_end(&mut decoded)
        .unwrap();
    assert_eq!(raw.as_ref(), decoded);
    h.insert("accept-encoding", "gzip;q=0".parse().unwrap());
    assert!(
        !presentation::docs::asset("/docs/assets/scalar-1.76.0.js", &h)
            .headers()
            .contains_key("content-encoding")
    );
}
