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
        settings,
        client,
        logs,
        recordings: std::sync::Arc::default(),
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
    let dal::database::Database::Sqlite(pool) = &s.db else {
        unreachable!()
    };
    sqlx::raw_sql(&include_str!("../migrations/001_app_catalog.sql").replace("public.", ""))
        .execute(pool)
        .await
        .unwrap();
    sqlx::query("INSERT INTO defaultdb_app(id,name) VALUES('reports','Reports')")
        .execute(pool)
        .await
        .unwrap();
    assert!(
        domain::support::create(&s, &a, &json!({"source_app":"unknown","body":"Hello"}))
            .await
            .unwrap()
            .is_none()
    );
    let t = domain::support::create(&s, &a, &json!({"source_app":" Reports ","body":"Hello"}))
        .await
        .unwrap()
        .unwrap();
    assert_eq!(t["source_app"], "reports");
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

#[tokio::test]
async fn annotations_boundary_forwards_public_requests_and_rejects_non_admin_writes() {
    use axum::{Router, extract::Request as Incoming, routing::any};
    let upstream = Router::new().fallback(any(|request: Incoming| async move {
        let ip = request
            .headers()
            .get("x-forwarded-for")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();
        let level = request
            .headers()
            .get("x-access-level")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("")
            .to_string();
        let path = request.uri().to_string();
        let bytes = to_bytes(request.into_body(), 51_000_000).await.unwrap();
        axum::Json(json!({"ip":ip,"level":level,"path":path,"bytes":bytes.len()}))
    }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, upstream).await.unwrap();
    });
    let mut s = state().await;
    Arc::make_mut(&mut s.settings.values)
        .insert("ANNOTATIONS_UPSTREAM".into(), format!("http://{address}"));
    // Environment policy tables from older deployments cannot override this boundary.
    Arc::make_mut(&mut s.settings.values).insert("PUBLIC_PROXY_ROUTES".into(), "{}".into());
    let (_, v) = call(
        s.clone(),
        "GET",
        "/apps/annotations/v1/posts?lang=th",
        json!({}),
        &[("cf-connecting-ip", "203.0.113.8"), ("x-access-level", "1")],
    )
    .await;
    assert_eq!(v["path"], "/posts?lang=th");
    assert_eq!(v["ip"], "203.0.113.8");
    assert_eq!(v["level"], "");
    assert_eq!(
        call(
            s.clone(),
            "PUT",
            "/apps/annotations/v1/admin/posts/a",
            json!({}),
            &[]
        )
        .await
        .0,
        403
    );
    s.cache
        .set(
            "exchange_auth_app:ordinary",
            json!({"access_level":3,"csrf_token":"c"}),
            60,
            false,
        )
        .await
        .unwrap();
    assert_eq!(
        call(
            s.clone(),
            "PUT",
            "/apps/annotations/v1/admin/posts/a",
            json!({}),
            &[("cookie", "sid=ordinary; csrf=c"), ("x-csrf-token", "c")]
        )
        .await
        .0,
        403
    );
    let (status, admin) = call(
        s.clone(),
        "PUT",
        "/apps/annotations/v1/admin/posts/a",
        json!({}),
        &[("authorization", "test-admin")],
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(admin["level"], "1");
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/annotations/v1/instant/phone/items",
            json!({"text":"hello"}),
            &[]
        )
        .await
        .0,
        200
    );
    assert_eq!(
        call(
            s,
            "POST",
            "/apps/annotations/v1/instant/phone/files?size=12",
            json!({}),
            &[("content-length", "51000000")]
        )
        .await
        .0,
        413
    );
    task.abort();
}
#[tokio::test]
async fn user_list_requires_an_administrator() {
    let s = state().await;
    for (sid, level) in [("user", 3), ("admin", 1)] {
        s.cache
            .set(
                &format!("exchange_auth_app:{sid}"),
                json!({"user_uuid_id":sid,"access_level":level,"csrf_token":"c"}),
                60,
                false,
            )
            .await
            .unwrap();
    }
    let list = |sid: &'static str| {
        let s = s.clone();
        async move {
            call(
                s,
                "GET",
                "/user/info/v1/all",
                json!({}),
                &[("cookie", &format!("sid={sid}"))],
            )
            .await
            .0
        }
    };
    assert_eq!(list("user").await, 403);
    assert_eq!(list("admin").await, 200);
    assert_eq!(
        call(s.clone(), "GET", "/user/info/v1/all", json!({}), &[])
            .await
            .0,
        403
    );
}
#[tokio::test]
async fn proxied_backends_never_receive_client_credentials() {
    use axum::{Router, extract::Request as Incoming, routing::any};
    let upstream = Router::new().fallback(any(|request: Incoming| async move {
        let h = request.headers();
        axum::Json(json!({
            "authorization": h.contains_key("authorization"),
            "cookie": h.contains_key("cookie"),
            "forwarded": h.contains_key("x-forwarded-for"),
        }))
    }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, upstream).await.unwrap();
    });
    let mut s = state().await;
    Arc::make_mut(&mut s.settings.values)
        .insert("DOMAIN_UPSTREAM".into(), format!("http://{address}"));
    let (status, v) = call(
        s,
        "GET",
        "/apps/domain/v1/projects",
        json!({}),
        &[("authorization", "test-admin"), ("cookie", "sid=anything")],
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(
        v,
        json!({"authorization":false,"cookie":false,"forwarded":true})
    );
    task.abort();
}
#[test]
fn secret_comparison_is_exact() {
    use domain::auth::same_secret;
    assert!(same_secret("test-admin", "test-admin"));
    assert!(!same_secret("test-admin", "test-admiN"));
    assert!(!same_secret("test-admin", "test-admin "));
    assert!(!same_secret("", "test-admin"));
}

#[tokio::test]
async fn reports_public_parent_never_opens_protected_children() {
    use axum::{Router, extract::Request as Incoming, routing::any};
    let upstream = Router::new().fallback(any(|request: Incoming| async move {
        axum::Json(json!({"path": request.uri().to_string()}))
    }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, upstream).await.unwrap();
    });
    let mut s = state().await;
    Arc::make_mut(&mut s.settings.values)
        .insert("REPORTS_UPSTREAM".into(), format!("http://{address}"));
    // Guest routes under the public "/projects/*" rule reach the engine.
    for path in [
        "/catalog",
        "/projects/cortex",
        "/projects/cortex/theme",
        "/projects/cortex/reports",
        "/projects/cortex/showcase/model-usage",
        "/projects/cortex/showcase/model-usage/cards/tokens",
        "/projects/cortex/showcase/model-usage/cards/tokens/embed",
    ] {
        let (status, v) = call(
            s.clone(),
            "GET",
            &format!("/apps/reports/v1{path}"),
            json!({}),
            &[],
        )
        .await;
        assert_eq!(status, 200, "{path} is public");
        assert_eq!(v["path"], path);
    }
    // Carved-out children of the public parent need a session, also with faked identity headers.
    for path in [
        "/projects/cortex/reports/model-usage",
        "/projects/cortex/reports/model-usage/cards/tokens",
        "/projects/cortex/reports/model-usage/datasets/tokens",
        "/projects/cortex/datasets/tokens",
        "/me",
        "/admin/projects/cortex/grants",
    ] {
        let (status, v) = call(
            s.clone(),
            "GET",
            &format!("/apps/reports/v1{path}"),
            json!({}),
            &[
                ("x-access-level", "1"),
                ("x-uuid", "fake"),
                ("x-project-admin", "true"),
            ],
        )
        .await;
        assert_eq!(status, 403, "{path} needs a session");
        assert!(v.get("path").is_none(), "{path} never reaches the engine");
    }
    // Admin writes need the administrator rule.
    for (method, path) in [
        ("PUT", "/projects/cortex/admin/project"),
        ("POST", "/projects/cortex/admin/ingest/telemetry_event"),
        ("DELETE", "/admin/fixtures/sample-v1-cortex"),
    ] {
        let (status, _) = call(
            s.clone(),
            method,
            &format!("/apps/reports/v1{path}"),
            json!({}),
            &[],
        )
        .await;
        assert_eq!(status, 403, "{method} {path} is admin only");
    }
    task.abort();
}

async fn log_state() -> domain::State {
    let s = state().await;
    if let dal::database::Database::Sqlite(pool) = &s.db {
        sqlx::query("PRAGMA foreign_keys=ON")
            .execute(pool)
            .await
            .unwrap();
        let catalog = include_str!("../migrations/001_app_catalog.sql")
            .replace("public.defaultdb_app", "defaultdb_app");
        let logs = include_str!("../migrations/002_app_logs.sql")
            .replace("public.defaultdb_app", "defaultdb_app")
            .replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT");
        sqlx::raw_sql(&format!("{catalog}\n{logs}"))
            .execute(pool)
            .await
            .unwrap();
    }
    s.db.sync_log_apps(&dal::remote::log_source::registered_apps())
        .await
        .unwrap();
    s
}
#[tokio::test]
async fn app_log_recording_is_admin_only_single_app_and_stop_preserves_streaming() {
    let s = log_state().await;
    for path in [
        "/apps/reports/v1/logs/stream",
        "/apps/annotations/v1/logs/stream",
        "/apps/api/v1/logs",
        "/apps/api/v1/logs/recordings",
    ] {
        assert_eq!(
            call(s.clone(), "GET", path, json!({}), &[]).await.0,
            403,
            "{path}"
        );
    }
    s.cache
        .set(
            "exchange_auth_app:regular",
            json!({"access_level":3,"csrf_token":"c"}),
            60,
            false,
        )
        .await
        .unwrap();
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/logs/recordings",
            json!({"app_id":"api_for_apps"}),
            &[("cookie", "sid=regular; csrf=c"), ("x-csrf-token", "c")]
        )
        .await
        .0,
        403
    );
    let admin = &[("authorization", "test-admin")][..];
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/logs/recordings",
            json!({"app_id":"not-registered"}),
            admin
        )
        .await
        .0,
        404
    );
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/logs/recordings",
            json!({"app_id":"api_for_apps"}),
            admin
        )
        .await
        .0,
        200
    );
    let mut live = s.logs.subscribe();
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/logs/recordings",
            json!({"app_id":"reports"}),
            admin
        )
        .await
        .0,
        409
    );
    s.logs
        .send("2026-10-27T00:00:00Z WARNING api_for_apps tests saved line".into())
        .unwrap();
    for _ in 0..30 {
        if !s
            .db
            .saved_logs(&Default::default())
            .await
            .unwrap()
            .is_empty()
        {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(5)).await;
    }
    let rows = s.db.saved_logs(&Default::default()).await.unwrap();
    assert_eq!(rows.len(), 1);
    assert_eq!(rows[0].level, "WARNING");
    assert_eq!(
        call(
            s.clone(),
            "DELETE",
            "/apps/api/v1/logs/recordings/api_for_apps",
            json!({}),
            admin
        )
        .await
        .0,
        200
    );
    s.logs.send("stream continues after stop".into()).unwrap();
    assert!(live.recv().await.unwrap().contains("saved line"));
    assert!(live.recv().await.unwrap().contains("continues"));
    assert_eq!(s.recordings.list()["recordings"], json!([]));
}
#[tokio::test]
async fn recordings_auto_stop_at_the_fixed_30_minute_deadline() {
    let s = log_state().await;
    // Startup queries SQLite on a worker thread. With paused time, Tokio can
    // auto-advance the pool timeout before that real worker answers.
    s.recordings.start(s.clone(), "api_for_apps").await.unwrap();
    tokio::time::pause();
    tokio::task::yield_now().await;
    tokio::time::advance(std::time::Duration::from_secs(
        core::logs::RECORDING_MAX_SECONDS - 1,
    ))
    .await;
    assert_eq!(
        s.recordings.list()["recordings"].as_array().unwrap().len(),
        1
    );
    // Tokio timers round to millisecond ticks. Cross that tick after the exact deadline.
    tokio::time::advance(std::time::Duration::from_millis(1001)).await;
    for _ in 0..5 {
        tokio::task::yield_now().await;
    }
    assert_eq!(s.recordings.list()["recordings"], json!([]));
}
#[tokio::test]
async fn saved_log_retention_removes_only_rows_older_than_15_days() {
    let s = log_state().await;
    let now = chrono::Utc::now();
    let cutoff = now - chrono::Duration::days(core::logs::SAVED_LOG_RETENTION_DAYS);
    s.db.insert_log(
        "reports",
        "INFO",
        "expired",
        cutoff - chrono::Duration::seconds(1),
    )
    .await
    .unwrap();
    s.db.insert_log("reports", "INFO", "boundary", cutoff)
        .await
        .unwrap();
    s.db.insert_log("annotations", "ERROR", "recent", now)
        .await
        .unwrap();
    let (_, visible) = call(
        s.clone(),
        "GET",
        "/apps/api/v1/logs",
        json!({}),
        &[("authorization", "test-admin")],
    )
    .await;
    assert!(
        visible["items"]
            .as_array()
            .unwrap()
            .iter()
            .all(|row| row["message"] != "expired")
    );
    assert_eq!(s.db.purge_logs_before(cutoff).await.unwrap(), 1);
    let rows = s.db.saved_logs(&Default::default()).await.unwrap();
    assert_eq!(rows.len(), 2);
    assert!(rows.iter().all(|r| r.message != "expired"));
    let (status, body) = call(
        s,
        "GET",
        "/apps/api/v1/logs?app_id=annotations&level=ERROR",
        json!({}),
        &[("authorization", "test-admin")],
    )
    .await;
    assert_eq!(status, 200, "{body}");
    assert_eq!(body["items"].as_array().unwrap().len(), 1);
}
#[tokio::test]
async fn app_stream_proxy_preserves_utf8_split_frames_without_forwarding_credentials() {
    use axum::body::Bytes;
    use axum::{Router, routing::get};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let app = Router::new().route(
        "/logs/stream",
        get(|headers: axum::http::HeaderMap| async move {
            assert!(!headers.contains_key("authorization"));
            assert!(!headers.contains_key("cookie"));
            let body =
                b"event: log\r\ndata: 2026-10-27T00:00:00Z INFO reports test ol\xc3\xa1\r\n\r\n";
            let chunks = vec![
                Ok::<_, std::io::Error>(Bytes::copy_from_slice(
                    &body[..body.iter().position(|byte| *byte == 0xc3).unwrap() + 1],
                )),
                Ok(Bytes::copy_from_slice(
                    &body[body.iter().position(|byte| *byte == 0xc3).unwrap() + 1..],
                )),
            ];
            (
                [("content-type", "text/event-stream")],
                Body::from_stream(futures_util::stream::iter(chunks)),
            )
        }),
    );
    let server = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });
    let mut s = log_state().await;
    Arc::make_mut(&mut s.settings.values)
        .insert("REPORTS_UPSTREAM".into(), format!("http://{address}"));
    let mut req = Request::builder()
        .uri("/apps/reports/v1/logs/stream")
        .header("authorization", "test-admin")
        .body(Body::empty())
        .unwrap();
    req.extensions_mut().insert(ConnectInfo(
        "127.0.0.1:5000".parse::<std::net::SocketAddr>().unwrap(),
    ));
    let response = presentation::router(s).oneshot(req).await.unwrap();
    assert_eq!(response.status(), 200);
    assert_eq!(response.headers()["cache-control"], "no-store");
    let bytes = to_bytes(response.into_body(), 10000).await.unwrap();
    assert!(String::from_utf8(bytes.to_vec()).unwrap().contains("olá"));
    server.abort();
}

#[tokio::test]
async fn app_log_foreign_keys_levels_and_inactive_flags_are_enforced() {
    let s = log_state().await;
    assert!(
        s.db.insert_log("unknown-app", "INFO", "invalid", chrono::Utc::now())
            .await
            .is_err()
    );
    assert!(
        s.db.insert_log("reports", "TRACE", "invalid", chrono::Utc::now())
            .await
            .is_err()
    );
    if let dal::database::Database::Sqlite(pool) = &s.db {
        sqlx::query("UPDATE defaultdb_app SET is_active=FALSE WHERE id='reports'")
            .execute(pool)
            .await
            .unwrap();
    }
    s.db.sync_log_apps(&dal::remote::log_source::registered_apps())
        .await
        .unwrap();
    assert!(!s.db.log_app_active("reports").await.unwrap());
    assert_eq!(
        s.recordings
            .start(s.clone(), "reports")
            .await
            .unwrap_err()
            .0,
        404
    );
    let (status, _) = call(
        s,
        "GET",
        "/apps/api/v1/logs?level=TRACE",
        json!({}),
        &[("authorization", "test-admin")],
    )
    .await;
    assert_eq!(status, 422);
}

async fn telemetry_state() -> domain::State {
    let state = state().await;
    let dal::database::Database::Sqlite(pool) = &state.db else {
        unreachable!()
    };
    sqlx::query("CREATE UNIQUE INDEX user_uuid_fixture ON defaultdb_user(uuid_id)")
        .execute(pool)
        .await
        .unwrap();
    sqlx::raw_sql(
        include_str!("../migrations/001_app_catalog.sql")
            .replace("public.", "")
            .as_str(),
    )
    .execute(pool)
    .await
    .unwrap();
    let schema = include_str!("../migrations/003_client_telemetry.sql")
        .replace("public.", "")
        .replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT");
    sqlx::raw_sql(&schema).execute(pool).await.unwrap();
    state
        .db
        .sync_log_apps(&[("annotations".into(), "Annotations".into())])
        .await
        .unwrap();
    state
}
fn event_batch() -> Value {
    json!({"app_id":"annotations","session_id":"22222222-2222-4222-8222-222222222222","locale":"en","theme":"dark","viewport_width":1280,"viewport_height":800,"events":[{"seq":0,"event_type":"input","screen":"article","route":"/article/:slug","path":"/article/example?token=should-not-store","element_id":"article.search.input","element_label":"Search articles","element_path":"article > content > search","value":"RAG study"}]})
}
#[tokio::test]
async fn telemetry_is_relational_idempotent_and_admin_only() {
    let s = telemetry_state().await;
    let batch = event_batch();
    let (status, first) = call(
        s.clone(),
        "POST",
        "/apps/api/v1/telemetry/events",
        batch.clone(),
        &[
            ("User-Agent", "Fixture browser"),
            ("CF-Connecting-IP", "203.0.113.9"),
        ],
    )
    .await;
    assert_eq!(status, 202);
    assert_eq!(first["accepted"], 1);
    let (_, again) = call(
        s.clone(),
        "POST",
        "/apps/api/v1/telemetry/events",
        batch,
        &[],
    )
    .await;
    assert_eq!(again["accepted"], 0);
    for kind in ["events", "errors", "sessions"] {
        assert_eq!(
            call(
                s.clone(),
                "GET",
                &format!("/apps/api/v1/telemetry/{kind}"),
                json!({}),
                &[]
            )
            .await
            .0,
            403
        );
    }
    let (status, events) = call(
        s.clone(),
        "GET",
        "/apps/api/v1/telemetry/events",
        json!({}),
        &[("Authorization", "test-admin")],
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(events["items"].as_array().unwrap().len(), 1);
    assert_eq!(events["items"][0]["value"], "RAG study");
    assert_eq!(events["items"][0]["path"], "/article/example");
    let (_, sessions) = call(
        s.clone(),
        "GET",
        "/apps/api/v1/telemetry/sessions",
        json!({}),
        &[("Authorization", "test-admin")],
    )
    .await;
    assert_eq!(sessions["items"][0]["ip"], "203.0.113.9");
    assert_eq!(sessions["items"][0]["user_id"], Value::Null);
    let mut bad = event_batch();
    bad["user_id"] = json!("forged");
    assert_eq!(
        call(s.clone(), "POST", "/apps/api/v1/telemetry/events", bad, &[])
            .await
            .0,
        422
    );
    let mut bad = event_batch();
    bad["ip"] = json!("1.1.1.1");
    assert_eq!(
        call(s.clone(), "POST", "/apps/api/v1/telemetry/events", bad, &[])
            .await
            .0,
        422
    );
    let mut bad = event_batch();
    bad["events"][0]["element_id"] = json!("RenderObject#99");
    assert_eq!(
        call(s, "POST", "/apps/api/v1/telemetry/events", bad, &[])
            .await
            .0,
        422
    );
}
#[tokio::test]
async fn telemetry_drops_sensitive_values_and_derives_user() {
    let s = telemetry_state().await;
    let dal::database::Database::Sqlite(pool) = &s.db else {
        unreachable!()
    };
    sqlx::query("INSERT INTO defaultdb_user(id,uuid_id) VALUES(10,'real-user')")
        .execute(pool)
        .await
        .unwrap();
    s.cache
        .set(
            "exchange_auth_app:real",
            json!({"user_uuid_id":"real-user","access_level":3}),
            60,
            false,
        )
        .await
        .unwrap();
    let mut batch = event_batch();
    batch["events"][0]["sensitive"] = json!(true);
    batch["events"][0]["value"] = json!("must-not-leave-device");
    let headers = [("Cookie", "sid=real")];
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/telemetry/events",
            batch.clone(),
            &headers
        )
        .await
        .0,
        202
    );
    let (_, sessions) = call(
        s.clone(),
        "GET",
        "/apps/api/v1/telemetry/sessions",
        json!({}),
        &[("Authorization", "test-admin")],
    )
    .await;
    assert_eq!(sessions["items"][0]["user_id"], "real-user");
    let (_, events) = call(
        s.clone(),
        "GET",
        "/apps/api/v1/telemetry/events",
        json!({}),
        &[("Authorization", "test-admin")],
    )
    .await;
    assert_eq!(events["items"][0]["value"], Value::Null);
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/telemetry/events",
            batch,
            &[]
        )
        .await
        .0,
        409
    );
    let mut batch = event_batch();
    batch["session_id"] = json!("33333333-3333-4333-8333-333333333333");
    batch["events"][0]["element_id"] = json!("login.password.input");
    batch["events"][0]["value"] = json!("password-value");
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/telemetry/events",
            batch,
            &[]
        )
        .await
        .0,
        202
    );
    let (_, events) = call(
        s,
        "GET",
        "/apps/api/v1/telemetry/events",
        json!({}),
        &[("Authorization", "test-admin")],
    )
    .await;
    assert_eq!(events["items"][0]["value"], Value::Null);
}
#[tokio::test]
async fn telemetry_limits_and_errors_use_sql_including_legacy() {
    let s = telemetry_state().await;
    let error = json!({"app_id":"annotations","session_id":"22222222-2222-4222-8222-222222222222","route":"/notes?secret=never","error_type":"FlutterError","message":"Bearer sensitive-value","stack":"trace","build_version":"1.1.0"});
    assert_eq!(
        call(
            s.clone(),
            "POST",
            "/apps/api/v1/telemetry/errors",
            error.clone(),
            &[]
        )
        .await
        .0,
        202
    );
    let (_, errors) = call(
        s.clone(),
        "GET",
        "/apps/api/v1/telemetry/errors",
        json!({}),
        &[("Authorization", "test-admin")],
    )
    .await;
    assert!(!errors.to_string().contains("sensitive-value"));
    assert_eq!(errors["items"][0]["route"], "/notes");
    let mut bad = error.clone();
    bad["user_id"] = json!("fake");
    assert_eq!(
        call(s.clone(), "POST", "/apps/api/v1/telemetry/errors", bad, &[])
            .await
            .0,
        422
    );
    let mut bad = error.clone();
    bad["message"] = json!("x".repeat(70_000));
    assert_eq!(
        call(s.clone(), "POST", "/apps/api/v1/telemetry/errors", bad, &[])
            .await
            .0,
        413
    );
    let mut bad = event_batch();
    bad["events"] = json!(vec![bad["events"][0].clone(); 51]);
    assert_eq!(
        call(s.clone(), "POST", "/apps/api/v1/telemetry/events", bad, &[])
            .await
            .0,
        422
    );
    let mut bad = event_batch();
    bad["app_id"] = json!("unknown");
    assert_eq!(
        call(s.clone(), "POST", "/apps/api/v1/telemetry/events", bad, &[])
            .await
            .0,
        422
    );
    assert_eq!(call(s.clone(),"POST","/apps/api/v1/client-error",json!({"app_name":"Annotations","error_title":"Legacy error","error_message":"Compatibility"}),&[]).await.0,202);
    assert_eq!(
        call(
            s.clone(),
            "GET",
            "/apps/api/v1/telemetry/errors?limit=201",
            json!({}),
            &[("Authorization", "test-admin")]
        )
        .await
        .0,
        422
    );
    for _ in 0..120 {
        s.cache
            .increment("ratelimit:tracking:198.51.100.5", 60)
            .await
            .unwrap();
    }
    assert_eq!(
        call(
            s,
            "POST",
            "/apps/api/v1/telemetry/errors",
            error,
            &[("CF-Connecting-IP", "198.51.100.5")]
        )
        .await
        .0,
        429
    );
}
#[test]
fn telemetry_does_not_trust_forwarded_ip_from_direct_peers() {
    let mut headers = axum::http::HeaderMap::new();
    headers.insert("cf-connecting-ip", "1.2.3.4".parse().unwrap());
    assert_eq!(
        domain::services::telemetry::client_ip(&headers, "198.51.100.6".parse().unwrap()),
        "198.51.100.6"
    );
}

#[tokio::test]
async fn cortex_log_source_reads_sse_without_websocket_upgrade() {
    use axum::{Router, http::HeaderMap, routing::get};
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let upstream = Router::new().route(
        "/logs/stream",
        get(|headers: HeaderMap| async move {
            assert!(!headers.contains_key("upgrade"));
            assert!(!headers.contains_key("authorization"));
            assert!(!headers.contains_key("cookie"));
            assert_eq!(headers["accept"], "text/event-stream");
            (
                [("content-type", "text/event-stream")],
                "event: log\ndata: ready\n\nevent: gap\ndata: 3 missed\n\n",
            )
        }),
    );
    let task = tokio::spawn(async move { axum::serve(listener, upstream).await.unwrap() });
    let mut s = state().await;
    let mut values = (*s.settings.values).clone();
    values.insert("CORTEX_UPSTREAM".into(), format!("http://{address}"));
    s.settings.values = Arc::new(values);
    let mut source = dal::remote::log_source::open(&s, "cortex").await.unwrap();
    assert!(matches!(
        source,
        dal::remote::log_source::Source::Sse { .. }
    ));
    let first = source.next().await.unwrap().unwrap();
    assert!(!first.gap);
    assert_eq!(first.line, "ready");
    let second = source.next().await.unwrap().unwrap();
    assert!(second.gap);
    assert_eq!(second.line, "3 missed");
    assert!(source.next().await.unwrap().is_none());
    task.abort();
}

// Installed-app login handoff (FINAL v2). Local Supabase double and the memory cache only.
mod native_handoff {
    use super::*;
    use crate::domain::auth;
    use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
    use sha2::{Digest, Sha256};
    use std::sync::atomic::{AtomicUsize, Ordering};
    static REQUESTS: AtomicUsize = AtomicUsize::new(0);
    const DAY: i64 = 24 * 60 * 60;

    async fn native_state(extra: &[(&str, &str)]) -> (domain::State, tokio::task::JoinHandle<()>) {
        use axum::routing::{get, post};
        let provider = axum::Router::new()
            .route(
                "/auth/v1/token",
                post(|| async { axum::Json(json!({"access_token":"native-access"})) }),
            )
            .route(
                "/auth/v1/user",
                get(|| async {
                    axum::Json(json!({"id":"native-provider-user","email":"native@example.test","user_metadata":{}}))
                }),
            );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let task = tokio::spawn(async move { axum::serve(listener, provider).await.unwrap() });
        let mut s = state().await;
        let mut values = (*s.settings.values).clone();
        values.insert("SUPABASE_URL".into(), format!("http://{address}"));
        values.insert("SUPABASE_SECRET_KEY".into(), "fixture".into());
        for (k, v) in extra {
            values.insert((*k).into(), (*v).into());
        }
        s.settings.values = Arc::new(values);
        (s, task)
    }
    /// handoff_id, secret, challenge = base64url(SHA256(raw secret bytes)).
    fn device() -> (String, String, String) {
        let secret: [u8; 32] = rand::random();
        (
            URL_SAFE_NO_PAD.encode(rand::random::<[u8; 32]>()),
            URL_SAFE_NO_PAD.encode(secret),
            URL_SAFE_NO_PAD.encode(Sha256::digest(secret)),
        )
    }
    /// The browser or app address comes from cf-connecting-ip behind the local tunnel.
    /// The same address is the per-IP rate key, so the network match and the limiter agree.
    async fn send(
        s: &domain::State,
        method: &str,
        path: &str,
        body: Value,
        network_ip: &str,
        cookie: Option<&str>,
    ) -> (StatusCode, Value) {
        let mut headers = vec![("cf-connecting-ip", network_ip)];
        let csrf;
        if let Some(cookie) = cookie {
            headers.push(("cookie", cookie));
            csrf = cookie.split("csrf=").nth(1).unwrap_or("").to_owned();
            headers.push(("x-csrf-token", csrf.as_str()));
        }
        call(s.clone(), method, path, body, &headers).await
    }
    async fn login(
        s: &domain::State,
        app: &str,
        id: &str,
        challenge: &str,
        platform: &str,
        ip: &str,
    ) -> (StatusCode, Value) {
        let n = REQUESTS.fetch_add(1, Ordering::Relaxed);
        let body = json!({"email":format!("native-{n}@example.test"),"password":"fixture","app":app,"handoff_id":id,"challenge":challenge,"platform":platform});
        send(s, "PATCH", "/user/sync/v1/log-in", body, ip, None).await
    }
    async fn finish(
        s: &domain::State,
        app: &str,
        id: &str,
        secret: &str,
        ip: &str,
    ) -> (StatusCode, Value) {
        send(
            s,
            "POST",
            "/apps/api/v1/exchange",
            json!({"app":app,"handoff_id":id,"secret":secret}),
            ip,
            None,
        )
        .await
    }
    fn code(r: &(StatusCode, Value)) -> (u16, String) {
        (
            r.0.as_u16(),
            r.1["data"]["code"].as_str().unwrap_or("").to_owned(),
        )
    }
    async fn record(s: &domain::State, id: &str) -> Value {
        s.cache
            .get(&format!("handoff:{id}"), false)
            .await
            .unwrap()
            .unwrap()
    }

    #[tokio::test]
    async fn trusted_browser_location_survives_finish_and_retry() {
        let (s, task) = native_state(&[]).await;
        for (peer, city, country, expected) in [
            (
                "127.0.0.1",
                Some("Bangkok"),
                Some("TH"),
                json!({"city":"Bangkok","country":"TH"}),
            ),
            ("::1", None, Some("BR"), json!({"country":"BR"})),
            ("198.51.100.1", Some("spoof"), Some("US"), Value::Null),
            ("127.0.0.1", None, None, Value::Null),
        ] {
            let (id, secret, challenge) = device();
            let mut headers = axum::http::HeaderMap::new();
            if let Some(city) = city {
                headers.insert("cf-ipcity", city.parse().unwrap());
            }
            if let Some(country) = country {
                headers.insert("cf-ipcountry", country.parse().unwrap());
            }
            let handoff = auth::HandoffRequest {
                id: id.clone(),
                challenge,
                platform: "linux".into(),
            };
            auth::complete_login(
                &s,
                "native-access",
                "annotations",
                Some(&handoff),
                &headers,
                peer,
            )
            .await
            .unwrap();
            let v = json!({"app":"annotations","handoff_id":id,"secret":secret});
            for _ in 0..2 {
                let result = auth::finish_handoff(&s, &v, &axum::http::HeaderMap::new(), peer)
                    .await
                    .unwrap();
                assert_eq!(result["location"], expected);
                let message = auth::handoff_success_message(&result, &v);
                assert_eq!(
                    message,
                    if expected.is_null() {
                        "Logged in"
                    } else if expected["city"].is_null() {
                        "Logged in from BR"
                    } else {
                        "Logged in from Bangkok, TH"
                    }
                );
            }
        }
        task.abort();
    }

    #[tokio::test]
    async fn app_cancel_blocks_late_browser_login_and_finish() {
        for before_login in [true, false] {
            let (s, task) = native_state(&[]).await;
            let (id, secret, challenge) = device();
            if !before_login {
                assert_eq!(
                    login(&s, "annotations", &id, &challenge, "linux", "203.0.113.1")
                        .await
                        .0,
                    200
                );
            }
            let cancel = json!({"app":"annotations","handoff_id":id,"secret":secret,"cancel":true});
            let mut wrong = cancel.clone();
            wrong["secret"] = json!(device().1);
            if !before_login {
                assert_eq!(
                    code(
                        &send(
                            &s,
                            "POST",
                            "/apps/api/v1/exchange",
                            wrong,
                            "203.0.113.1",
                            None
                        )
                        .await
                    )
                    .1,
                    "INVALID_HANDOFF"
                );
                assert_eq!(record(&s, &id).await["status"], "done");
            }
            for _ in 0..2 {
                let r = send(
                    &s,
                    "POST",
                    "/apps/api/v1/exchange",
                    cancel.clone(),
                    "203.0.113.1",
                    None,
                )
                .await;
                assert_eq!(r.0, 200);
                assert_eq!(r.1["data"], json!({"status":"cancelled"}));
            }
            assert_eq!(
                code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await).1,
                "HANDOFF_CANCELLED"
            );
            assert_eq!(
                code(&login(&s, "annotations", &id, &challenge, "linux", "203.0.113.1").await).1,
                "HANDOFF_CANCELLED"
            );
            let status =
                json!({"app":"annotations","handoff_id":id,"challenge":challenge,"status":true});
            let e = auth::finish_handoff(&s, &status, &axum::http::HeaderMap::new(), "127.0.0.1")
                .await
                .unwrap_err();
            assert_eq!(
                e.downcast_ref::<auth::HandoffFailure>(),
                Some(&auth::HandoffFailure::Cancelled)
            );
            task.abort();
        }
    }

    #[tokio::test]
    async fn browser_status_contains_no_credentials_and_requires_matching_challenge() {
        let (s, task) = native_state(&[]).await;
        let (id, secret, challenge) = device();
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "linux", "203.0.113.1")
                .await
                .0,
            200
        );
        let status =
            json!({"app":"annotations","handoff_id":id,"challenge":challenge,"status":true});
        let r = send(
            &s,
            "POST",
            "/apps/api/v1/exchange",
            status.clone(),
            "203.0.113.1",
            None,
        )
        .await;
        assert_eq!(r.0, 200);
        assert_eq!(r.1["data"].as_object().unwrap().len(), 2);
        assert_eq!(r.1["data"]["status"], "done");
        let mut wrong = status.clone();
        wrong["challenge"] = json!(device().2);
        assert_eq!(
            code(
                &send(
                    &s,
                    "POST",
                    "/apps/api/v1/exchange",
                    wrong,
                    "203.0.113.1",
                    None
                )
                .await
            )
            .1,
            "INVALID_HANDOFF"
        );
        let r = finish(&s, "annotations", &id, &secret, "203.0.113.1").await;
        assert_eq!(r.0, 200);
        let r = send(
            &s,
            "POST",
            "/apps/api/v1/exchange",
            status,
            "203.0.113.1",
            None,
        )
        .await;
        assert_eq!(r.0, 200);
        assert_eq!(r.1["data"]["status"], "used");
        assert!(r.1["data"].get("session_id").is_none());
        task.abort();
    }

    #[tokio::test]
    async fn cancel_and_finish_race_has_one_terminal_outcome() {
        let s = state().await;
        for _ in 0..16 {
            let (id, secret, challenge) = device();
            let h = auth::HandoffRequest {
                id: id.clone(),
                challenge,
                platform: "linux".into(),
            };
            auth::store_handoff(
                &s,
                "annotations",
                &h,
                json!({"id":1}),
                "127.0.0.1".parse().unwrap(),
                Value::Null,
            )
            .await
            .unwrap();
            let v = json!({"app":"annotations","handoff_id":id,"secret":secret});
            let mut cancel = v.clone();
            cancel["cancel"] = json!(true);
            let headers = axum::http::HeaderMap::new();
            let (finish, cancel) = tokio::join!(
                auth::finish_handoff(&s, &v, &headers, "127.0.0.1"),
                auth::finish_handoff(&s, &cancel, &headers, "127.0.0.1")
            );
            assert_ne!(finish.is_ok(), cancel.is_ok());
            let saved = record(&s, &id).await;
            if cancel.is_ok() {
                assert_eq!(saved["status"], "cancelled");
                assert!(saved["session_id"].is_null());
            } else {
                assert_eq!(saved["status"], "used");
            }
        }
    }

    #[tokio::test]
    async fn login_stores_handoff_and_finish_returns_one_device_session() {
        let (s, task) = native_state(&[]).await;
        let (id, secret, challenge) = device();
        let r = login(&s, "annotations", &id, &challenge, "linux", "203.0.113.10").await;
        assert_eq!(r.0, 200, "{}", r.1);
        assert_eq!(r.1["message"], "Login complete. Return to the app.");
        let expires = r.1["data"]["expires_at"].as_i64().unwrap();
        assert!((expires - domain::auth::now() - 300).abs() <= 2);
        assert_eq!(
            r.1["data"].as_object().unwrap().len(),
            1,
            "no token in handoff mode"
        );
        let stored = record(&s, &id).await;
        assert_eq!(stored["status"], "done");
        assert_eq!(stored["network"], "203.0.113.0/24");
        assert_eq!(stored["ip"], "203.0.113.10");
        assert_eq!(stored["platform"], "linux");
        assert_eq!(stored["app"], "annotations");
        assert!(stored["session_id"].is_null() && stored["user"]["email"] == "native@example.test");

        // The same handoff_id cannot log in twice.
        let (_, _, other_challenge) = device();
        assert_eq!(
            code(
                &login(
                    &s,
                    "annotations",
                    &id,
                    &other_challenge,
                    "linux",
                    "203.0.113.10"
                )
                .await
            ),
            (409, "HANDOFF_USED".into())
        );

        // Finish from the same /24, without any Origin header.
        let r = finish(&s, "annotations", &id, &secret, "203.0.113.77").await;
        assert_eq!(r.0, 200, "{}", r.1);
        assert_eq!(r.1["message"], "Logged in");
        let sid = r.1["data"]["session_id"].as_str().unwrap().to_owned();
        let csrf = r.1["data"]["csrf_token"].as_str().unwrap().to_owned();
        assert_eq!(r.1["data"]["expires_in"], 30 * DAY);
        let stored = record(&s, &id).await;
        assert_eq!(stored["status"], "used");
        assert_eq!(stored["session_id"], sid.as_str());
        assert!(stored["used_at"].is_i64());

        // The current session code accepts the cookie pair from the app.
        let cookie = format!("sid={sid}; csrf={csrf}");
        let me = send(
            &s,
            "GET",
            "/user/info/v1/",
            json!({}),
            "203.0.113.77",
            Some(&cookie),
        )
        .await;
        assert_eq!(me.0, 200, "{}", me.1);
        assert_eq!(me.1["data"]["email"], "native@example.test");

        // Retry within 2 minutes: same secret and network give the same session.
        let again = finish(&s, "annotations", &id, &secret, "203.0.113.5").await;
        assert_eq!(again.0, 200);
        assert_eq!(again.1["data"]["session_id"], sid.as_str());
        assert_eq!(again.1["data"]["csrf_token"], csrf.as_str());
        // A retry with a wrong secret, wrong network or wrong app is refused and changes nothing.
        let (_, wrong_secret, _) = device();
        assert_eq!(
            code(&finish(&s, "annotations", &id, &wrong_secret, "203.0.113.5").await),
            (409, "HANDOFF_USED".into())
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "198.51.100.5").await),
            (409, "HANDOFF_USED".into())
        );
        assert_eq!(
            code(&finish(&s, "cortex", &id, &secret, "203.0.113.5").await),
            (409, "HANDOFF_USED".into())
        );
        assert_eq!(
            finish(&s, "annotations", &id, &secret, "203.0.113.5")
                .await
                .1["data"]["session_id"],
            sid.as_str()
        );

        // Log out ends this device session; the retry never restores it.
        let out = send(
            &s,
            "POST",
            "/user/sync/v1/log-out",
            json!({}),
            "203.0.113.77",
            Some(&cookie),
        )
        .await;
        assert_eq!(out.0, 200, "{}", out.1);
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.5").await),
            (409, "HANDOFF_USED".into())
        );
        assert!(
            s.cache
                .get(&format!("exchange_auth_app:{sid}"), false)
                .await
                .unwrap()
                .is_none()
        );
        task.abort();
    }

    #[tokio::test]
    async fn finish_answers_not_finished_expired_used_and_retry_window() {
        // Not finished: no record yet; the answer does not create one.
        let (s, task) = native_state(&[]).await;
        let (id, secret, challenge) = device();
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (409, "HANDOFF_NOT_FINISHED".into())
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (409, "HANDOFF_NOT_FINISHED".into())
        );
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "macos", "203.0.113.1")
                .await
                .0,
            200
        );
        assert_eq!(
            finish(&s, "annotations", &id, &secret, "203.0.113.1")
                .await
                .0,
            200
        );
        task.abort();

        // Expired: past expires_at the status becomes expired and stays expired.
        let (s, task) = native_state(&[("HANDOFF_VALID_SECONDS", "0")]).await;
        let (id, secret, challenge) = device();
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "android", "203.0.113.1")
                .await
                .0,
            200
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (410, "HANDOFF_EXPIRED".into())
        );
        assert_eq!(record(&s, &id).await["status"], "expired");
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (410, "HANDOFF_EXPIRED".into())
        );
        task.abort();

        // Used outside the retry window.
        let (s, task) = native_state(&[("HANDOFF_RETRY_SECONDS", "0")]).await;
        let (id, secret, challenge) = device();
        assert_eq!(
            login(&s, "cortex", &id, &challenge, "cli", "203.0.113.1")
                .await
                .0,
            200
        );
        assert_eq!(
            finish(&s, "cortex", &id, &secret, "203.0.113.1").await.0,
            200
        );
        assert_eq!(
            code(&finish(&s, "cortex", &id, &secret, "203.0.113.1").await),
            (409, "HANDOFF_USED".into())
        );
        task.abort();
    }

    #[tokio::test]
    async fn wrong_secret_network_or_app_burn_the_handoff() {
        let (s, task) = native_state(&[]).await;
        // Wrong secret: used, and the real secret cannot finish afterwards.
        let (id, secret, challenge) = device();
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "ios", "203.0.113.1")
                .await
                .0,
            200
        );
        let (_, wrong, _) = device();
        assert_eq!(
            code(&finish(&s, "annotations", &id, &wrong, "203.0.113.1").await),
            (409, "HANDOFF_USED".into())
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (409, "HANDOFF_USED".into())
        );
        assert!(record(&s, &id).await["session_id"].is_null());
        // Wrong IPv4 network (/24).
        let (id, secret, challenge) = device();
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "ipados", "203.0.113.1")
                .await
                .0,
            200
        );
        // Section 4.3: the first finish that fails only on the network says why.
        let refused = finish(&s, "annotations", &id, &secret, "203.0.114.1").await;
        assert_eq!(code(&refused), (403, "LOGIN_REFUSED_NETWORK".into()));
        assert_eq!(
            refused.1["message"],
            "Login refused. The login came from a different location."
        );
        assert_eq!(record(&s, &id).await["status"], "used");
        assert!(record(&s, &id).await["session_id"].is_null());
        // Later finishes on that record answer used, from any network.
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.114.1").await),
            (409, "HANDOFF_USED".into())
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (409, "HANDOFF_USED".into())
        );
        // Wrong secret from a wrong network proves nothing about the caller: plain used.
        let (id, _, challenge) = device();
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "linux", "203.0.113.1")
                .await
                .0,
            200
        );
        let (_, wrong, _) = device();
        assert_eq!(
            code(&finish(&s, "annotations", &id, &wrong, "203.0.114.1").await),
            (409, "HANDOFF_USED".into())
        );
        // Wrong application.
        let (id, secret, challenge) = device();
        assert_eq!(
            login(&s, "annotations", &id, &challenge, "android", "203.0.113.1")
                .await
                .0,
            200
        );
        assert_eq!(
            code(&finish(&s, "cortex", &id, &secret, "203.0.113.1").await),
            (409, "HANDOFF_USED".into())
        );
        // IPv6 compares the /64.
        let (id, secret, challenge) = device();
        assert_eq!(
            login(
                &s,
                "annotations",
                &id,
                &challenge,
                "linux",
                "2001:db8:1:2::1"
            )
            .await
            .0,
            200
        );
        assert_eq!(record(&s, &id).await["network"], "2001:db8:1:2::/64");
        assert_eq!(
            finish(&s, "annotations", &id, &secret, "2001:db8:1:2:aaaa::9")
                .await
                .0,
            200
        );
        let (id, secret, challenge) = device();
        assert_eq!(
            login(
                &s,
                "annotations",
                &id,
                &challenge,
                "linux",
                "2001:db8:1:2::1"
            )
            .await
            .0,
            200
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "2001:db8:1:3::1").await),
            (403, "LOGIN_REFUSED_NETWORK".into())
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "2001:db8:1:2::1").await),
            (409, "HANDOFF_USED".into())
        );
        // A direct client cannot pick its network: cf-connecting-ip counts only from the local tunnel.
        assert_eq!(
            domain::auth::client_ip(
                &{
                    let mut h = axum::http::HeaderMap::new();
                    h.insert("cf-connecting-ip", "203.0.113.1".parse().unwrap());
                    h
                },
                "198.51.100.6"
            )
            .unwrap()
            .to_string(),
            "198.51.100.6"
        );
        task.abort();
    }

    #[tokio::test]
    async fn invalid_fields_are_refused_and_web_login_is_unchanged() {
        let (s, task) = native_state(&[]).await;
        let (id, secret, challenge) = device();
        for (app, id, challenge, platform) in [
            ("annotations", "short", challenge.as_str(), "linux"),
            ("annotations", id.as_str(), "short", "linux"),
            ("annotations", id.as_str(), challenge.as_str(), "windows"),
            ("annotations", id.as_str(), challenge.as_str(), "cli"),
            ("reports", id.as_str(), challenge.as_str(), "linux"),
            ("unknown", id.as_str(), challenge.as_str(), "linux"),
        ] {
            assert_eq!(
                code(&login(&s, app, id, challenge, platform, "203.0.113.1").await),
                (400, "INVALID_HANDOFF".into()),
                "{app} {platform}"
            );
        }
        let missing = send(
            &s,
            "PATCH",
            "/user/sync/v1/log-in",
            json!({"email":"m@example.test","password":"x","app":"annotations","handoff_id":id}),
            "203.0.113.1",
            None,
        )
        .await;
        assert_eq!(code(&missing), (400, "INVALID_HANDOFF".into()));
        assert_eq!(
            code(&finish(&s, "annotations", &id, "short", "203.0.113.1").await),
            (400, "INVALID_HANDOFF".into())
        );
        assert_eq!(
            code(
                &send(
                    &s,
                    "POST",
                    "/apps/api/v1/exchange",
                    json!({"app":"annotations","handoff_id":id}),
                    "203.0.113.1",
                    None
                )
                .await
            ),
            (400, "INVALID_HANDOFF".into())
        );
        assert!(
            s.cache
                .get(&format!("handoff:{id}"), false)
                .await
                .unwrap()
                .is_none()
        );
        let _ = secret;
        // Web login without handoff_id still returns the exchange artifact as before.
        let web = send(&s, "PATCH", "/user/sync/v1/log-in", json!({"email":"web@example.test","password":"fixture","app":"reports","platform":"linux"}), "203.0.113.1", None).await;
        assert_eq!(web.0, 200);
        assert_eq!(web.1["message"], "User logged in successfully.");
        assert!(web.1["data"].is_string());
        task.abort();
    }

    #[tokio::test]
    async fn disabled_setting_turns_the_native_path_off() {
        let (s, task) = native_state(&[("NATIVE_HANDOFF_ENABLED", "false")]).await;
        let (id, secret, challenge) = device();
        assert_eq!(
            code(&login(&s, "annotations", &id, &challenge, "linux", "203.0.113.1").await),
            (403, "NATIVE_HANDOFF_DISABLED".into())
        );
        assert_eq!(
            code(&finish(&s, "annotations", &id, &secret, "203.0.113.1").await),
            (403, "NATIVE_HANDOFF_DISABLED".into())
        );
        let start = send(&s, "POST", "/user/sync/v1/oauth/start", json!({"provider":"google","app":"annotations","handoff_id":id,"challenge":challenge,"platform":"linux"}), "203.0.113.1", None).await;
        assert_eq!(code(&start), (403, "NATIVE_HANDOFF_DISABLED".into()));
        assert!(
            s.cache
                .get(&format!("handoff:{id}"), false)
                .await
                .unwrap()
                .is_none()
        );
        // Existing native sessions stop working; web sessions do not change.
        let at = domain::auth::now();
        s.cache.set("exchange_auth_app:native", json!({"user_id":1,"csrf_token":"c","native":true,"created_at":at,"last_used_at":at}), 60, false).await.unwrap();
        s.cache
            .set(
                "exchange_auth_app:web",
                json!({"user_id":1,"csrf_token":"c"}),
                60,
                false,
            )
            .await
            .unwrap();
        let mut h = axum::http::HeaderMap::new();
        h.insert("cookie", "sid=native".parse().unwrap());
        assert!(domain::auth::session(&s, &h).await.unwrap().is_none());
        h.insert("cookie", "sid=web".parse().unwrap());
        assert!(domain::auth::session(&s, &h).await.unwrap().is_some());
        let web = send(
            &s,
            "PATCH",
            "/user/sync/v1/log-in",
            json!({"email":"web@example.test","password":"fixture","app":"reports"}),
            "203.0.113.1",
            None,
        )
        .await;
        assert_eq!(web.0, 200);
        assert!(web.1["data"].is_string());
        task.abort();
    }

    #[tokio::test]
    async fn native_session_slides_30_days_and_ends_at_90_days() {
        let s = state().await;
        let at = domain::auth::now();
        let put = |sid: &'static str, created: i64, last: i64| {
            let s = s.clone();
            async move {
                s.cache.set(&format!("exchange_auth_app:{sid}"), json!({"user_id":1,"csrf_token":"c","native":true,"created_at":created,"last_used_at":last}), 60, false).await.unwrap();
            }
        };
        let get = |sid: &str| {
            let mut h = axum::http::HeaderMap::new();
            h.insert("cookie", format!("sid={sid}").parse().unwrap());
            let s = s.clone();
            async move { domain::auth::session(&s, &h).await.unwrap() }
        };
        let expiry = |sid: &str| {
            let dal::cache::Cache::Memory(m) = &s.cache else {
                unreachable!()
            };
            let m = m.clone();
            let key = format!("exchange_auth_app:{sid}");
            async move {
                m.lock()
                    .await
                    .get(&key)
                    .map(|x| x.1.duration_since(std::time::Instant::now()).as_secs())
            }
        };
        // Use renews the idle window to 30 days.
        put("active", at - 10 * DAY, at - 29 * DAY).await;
        let u = get("active").await.unwrap();
        assert_eq!(u["last_used_at"], at);
        assert!(expiry("active").await.unwrap() > (30 * DAY - 5) as u64);
        assert_eq!(get("active").await.unwrap()["created_at"], at - 10 * DAY);
        // Idle more than 30 days: ended and removed.
        put("idle", at - 40 * DAY, at - 30 * DAY - 1).await;
        assert!(get("idle").await.is_none());
        assert!(expiry("idle").await.is_none());
        // The renewal never passes the 90 day absolute limit.
        put("near", at - 90 * DAY + 100, at - DAY).await;
        assert!(get("near").await.is_some());
        assert!(expiry("near").await.unwrap() <= 100);
        // After 90 days: ended even when used recently.
        put("old", at - 90 * DAY - 1, at - 60).await;
        assert!(get("old").await.is_none());
        // Web sessions keep the current fixed TTL and record.
        s.cache
            .set(
                "exchange_auth_app:web",
                json!({"user_id":1,"csrf_token":"c"}),
                90000,
                false,
            )
            .await
            .unwrap();
        let web = get("web").await.unwrap();
        assert!(web.get("last_used_at").is_none());
    }

    #[tokio::test]
    async fn oauth_keeps_handoff_in_state_and_callback_finishes_without_token() {
        let (s, task) = native_state(&[]).await;
        let (id, secret, challenge) = device();
        let start = send(&s, "POST", "/user/sync/v1/oauth/start", json!({"provider":"google","app":"annotations","handoff_id":id,"challenge":challenge,"platform":"android"}), "203.0.113.1", None).await;
        assert_eq!(start.0, 200, "{}", start.1);
        let url = url::Url::parse(start.1["data"]["authorization_url"].as_str().unwrap()).unwrap();
        let state = url
            .query_pairs()
            .find(|(k, _)| k == "state")
            .unwrap()
            .1
            .into_owned();
        let stored = s
            .cache
            .get(&format!("oauth_state:{state}"), false)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(stored["handoff_id"], id.as_str());
        assert_eq!(stored["challenge"], challenge.as_str());
        assert_eq!(stored["platform"], "android");
        let cb = send(
            &s,
            "POST",
            "/user/sync/v1/oauth/callback",
            json!({"code":"fixture","state":state}),
            "203.0.113.1",
            None,
        )
        .await;
        assert_eq!(cb.0, 200, "{}", cb.1);
        assert_eq!(cb.1["message"], "Login complete. Return to the app.");
        assert!(cb.1["data"]["expires_at"].is_i64());
        assert_eq!(cb.1["data"].as_object().unwrap().len(), 1);
        assert_eq!(
            send(
                &s,
                "POST",
                "/user/sync/v1/oauth/callback",
                json!({"code":"fixture","state":state}),
                "203.0.113.1",
                None
            )
            .await
            .0,
            400
        );
        assert_eq!(
            finish(&s, "annotations", &id, &secret, "203.0.113.9")
                .await
                .0,
            200
        );
        task.abort();
    }

    #[tokio::test]
    async fn cache_compare_and_swap_is_conditional_and_msgpack_stable() {
        let c = dal::cache::Cache::new("memory://", "").await.unwrap();
        let v = json!({"status":"done","expires_at":1_800_000_000i64,"used_at":null,"user":{"id":3,"email":"a@b.c"}});
        c.set("h", v.clone(), 60, true).await.unwrap();
        let mut next = v.clone();
        next["status"] = json!("used");
        assert!(
            !c.compare_and_swap("h", &next, v.clone(), None, None)
                .await
                .unwrap()
        );
        assert!(
            c.compare_and_swap("h", &v, next.clone(), None, Some(("s", json!(1), 60)))
                .await
                .unwrap()
        );
        assert_eq!(c.get("s", false).await.unwrap(), Some(json!(1)));
        // A second swap from the old value loses, and an existing second key blocks the swap.
        assert!(
            !c.compare_and_swap("h", &v, next.clone(), None, None)
                .await
                .unwrap()
        );
        assert!(
            !c.compare_and_swap("h", &next, v.clone(), None, Some(("s", json!(2), 60)))
                .await
                .unwrap()
        );
        assert!(
            !c.compare_and_swap("missing", &v, next.clone(), None, None)
                .await
                .unwrap()
        );
        // The Valkey adapter compares encoded bytes: decoding and encoding again must not change them.
        let bytes = rmp_serde::to_vec_named(&v).unwrap();
        let back: Value = rmp_serde::from_slice(&bytes).unwrap();
        assert_eq!(rmp_serde::to_vec_named(&back).unwrap(), bytes);
    }
}

// Real Valkey check of the EVAL compare-and-swap path. Runs only when TEST_VALKEY_URL points
// at a disposable loopback instance (never the services' Valkey or Redis on port 6379).
mod valkey_handoff {
    use super::*;
    use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
    use domain::auth::{self, HandoffFailure, HandoffRequest};
    use sha2::{Digest, Sha256};

    fn test_url() -> Option<String> {
        let url = std::env::var("TEST_VALKEY_URL").ok()?;
        let parsed = url::Url::parse(&url).expect("TEST_VALKEY_URL");
        assert_eq!(
            parsed.host_str(),
            Some("127.0.0.1"),
            "loopback test instance only"
        );
        assert_ne!(
            parsed.port(),
            Some(6379),
            "never the services' Valkey or Redis"
        );
        Some(url)
    }
    struct Valkey {
        s: domain::State,
        raw: redis::aio::ConnectionManager,
        ns: String,
    }
    async fn valkey(url: &str, extra: &[(&str, &str)]) -> Valkey {
        let mut s = state().await;
        let ns = format!("test64:{}:", auth::token(8));
        s.cache = dal::cache::Cache::new(url, &ns).await.unwrap();
        let mut values = (*s.settings.values).clone();
        for (k, v) in extra {
            values.insert((*k).into(), (*v).into());
        }
        s.settings.values = Arc::new(values);
        let raw = redis::Client::open(url)
            .unwrap()
            .get_connection_manager()
            .await
            .unwrap();
        Valkey { s, raw, ns }
    }
    impl Valkey {
        async fn ttl(&self, key: &str) -> i64 {
            let mut c = self.raw.clone();
            redis::cmd("TTL")
                .arg(format!("{}{key}", self.ns))
                .query_async(&mut c)
                .await
                .unwrap()
        }
        async fn sessions(&self) -> Vec<String> {
            let mut c = self.raw.clone();
            redis::cmd("KEYS")
                .arg(format!("{}exchange_auth_app:*", self.ns))
                .query_async(&mut c)
                .await
                .unwrap()
        }
        async fn record(&self, id: &str) -> Value {
            self.s
                .cache
                .get(&format!("handoff:{id}"), false)
                .await
                .unwrap()
                .unwrap()
        }
        async fn cleanup(&self) {
            let mut c = self.raw.clone();
            let keys: Vec<String> = redis::cmd("KEYS")
                .arg(format!("{}*", self.ns))
                .query_async(&mut c)
                .await
                .unwrap();
            if !keys.is_empty() {
                let _: u64 = redis::cmd("DEL")
                    .arg(keys)
                    .query_async(&mut c)
                    .await
                    .unwrap();
            }
        }
    }
    fn device() -> (HandoffRequest, String) {
        let secret: [u8; 32] = rand::random();
        (
            HandoffRequest {
                id: URL_SAFE_NO_PAD.encode(rand::random::<[u8; 32]>()),
                challenge: URL_SAFE_NO_PAD.encode(Sha256::digest(secret)),
                platform: "linux".into(),
            },
            URL_SAFE_NO_PAD.encode(secret),
        )
    }
    fn user() -> Value {
        json!({"app":"annotations","provider":"supabase","id":7,"uuid_id":"u7","email":"valkey@example.test","access_level":3,"is_active":true,"provider_user_id":"p7"})
    }
    async fn store(v: &Valkey, h: &HandoffRequest, ip: &str) -> anyhow::Result<i64> {
        auth::store_handoff(
            &v.s,
            "annotations",
            h,
            user(),
            ip.parse().unwrap(),
            Value::Null,
        )
        .await
    }
    async fn finish(
        v: &Valkey,
        h: &HandoffRequest,
        secret: &str,
        ip: &str,
    ) -> Result<Value, HandoffFailure> {
        let mut headers = axum::http::HeaderMap::new();
        headers.insert("cf-connecting-ip", ip.parse().unwrap());
        auth::finish_handoff(
            &v.s,
            &json!({"app":"annotations","handoff_id":h.id,"secret":secret}),
            &headers,
            "127.0.0.1",
        )
        .await
        .map_err(|e| *e.downcast_ref::<HandoffFailure>().expect("handoff answer"))
    }

    #[tokio::test]
    async fn valkey_store_finish_retry_and_session_renewal() {
        let Some(url) = test_url() else {
            eprintln!("TEST_VALKEY_URL not set: Valkey integration test skipped");
            return;
        };
        let v = valkey(&url, &[]).await;
        let (h, secret) = device();
        // SET NX handoff store with the 30 minute record TTL.
        assert!(store(&v, &h, "203.0.113.10").await.is_ok());
        let ttl = v.ttl(&format!("handoff:{}", h.id)).await;
        assert!((1795..=1800).contains(&ttl), "record ttl {ttl}");
        assert_eq!(
            store(&v, &h, "203.0.113.10")
                .await
                .unwrap_err()
                .downcast_ref::<HandoffFailure>(),
            Some(&HandoffFailure::Used)
        );
        assert_eq!(v.record(&h.id).await["status"], "done");
        // Finish success through EVAL: status used, record TTL kept, session created.
        let done = finish(&v, &h, &secret, "203.0.113.99").await.unwrap();
        let sid = done["session_id"].as_str().unwrap().to_owned();
        let record = v.record(&h.id).await;
        assert_eq!(record["status"], "used");
        assert_eq!(record["session_id"], sid.as_str());
        let ttl = v.ttl(&format!("handoff:{}", h.id)).await;
        assert!((1790..=1800).contains(&ttl), "KEEPTTL kept {ttl}");
        let session_ttl = v.ttl(&format!("exchange_auth_app:{sid}")).await;
        assert!(session_ttl > 30 * 86400 - 10, "session ttl {session_ttl}");
        // Retry window: same secret and network give the same session; wrong network is used.
        assert_eq!(
            finish(&v, &h, &secret, "203.0.113.5").await.unwrap()["session_id"],
            sid.as_str()
        );
        assert_eq!(
            finish(&v, &h, &secret, "198.51.100.5").await,
            Err(HandoffFailure::Used)
        );
        assert_eq!(v.sessions().await.len(), 1);
        // Native session renewal through EVAL with a new TTL.
        let key = format!("exchange_auth_app:{sid}");
        let mut u = v.s.cache.get(&key, false).await.unwrap().unwrap();
        let at = auth::now();
        u["last_used_at"] = json!(at - 86400);
        v.s.cache.set(&key, u, 60, false).await.unwrap();
        let mut hm = axum::http::HeaderMap::new();
        hm.insert("cookie", format!("sid={sid}").parse().unwrap());
        let renewed = auth::session(&v.s, &hm).await.unwrap().unwrap();
        assert!(renewed["last_used_at"].as_i64().unwrap() >= at);
        assert!(v.ttl(&key).await > 30 * 86400 - 10);
        // Revoked session: the retry answers used and never restores it.
        v.s.cache.delete(&key).await.unwrap();
        assert_eq!(
            finish(&v, &h, &secret, "203.0.113.5").await,
            Err(HandoffFailure::Used)
        );
        assert!(v.sessions().await.is_empty());
        v.cleanup().await;
    }

    #[tokio::test]
    async fn valkey_concurrent_finishes_create_one_session() {
        let Some(url) = test_url() else {
            eprintln!("TEST_VALKEY_URL not set: Valkey integration test skipped");
            return;
        };
        // Without a retry window exactly one concurrent finish wins.
        let v = valkey(&url, &[("HANDOFF_RETRY_SECONDS", "0")]).await;
        let (h, secret) = device();
        store(&v, &h, "203.0.113.10").await.unwrap();
        let results = futures_util::future::join_all(
            (0..16).map(|_| finish(&v, &h, &secret, "203.0.113.10")),
        )
        .await;
        assert_eq!(
            results.iter().filter(|r| r.is_ok()).count(),
            1,
            "{results:?}"
        );
        assert!(
            results
                .iter()
                .all(|r| r.is_ok() || *r == Err(HandoffFailure::Used))
        );
        assert_eq!(v.sessions().await.len(), 1);
        v.cleanup().await;
        // With the retry window the losers get the winner's session, still only one session.
        let v = valkey(&url, &[]).await;
        let (h, secret) = device();
        store(&v, &h, "203.0.113.10").await.unwrap();
        let results = futures_util::future::join_all(
            (0..16).map(|_| finish(&v, &h, &secret, "203.0.113.10")),
        )
        .await;
        let ids: std::collections::HashSet<String> = results
            .iter()
            .map(|r| {
                r.as_ref().unwrap()["session_id"]
                    .as_str()
                    .unwrap()
                    .to_owned()
            })
            .collect();
        assert_eq!(ids.len(), 1);
        assert_eq!(v.sessions().await.len(), 1);
        v.cleanup().await;
    }

    #[tokio::test]
    async fn valkey_expired_and_network_refusal_keep_the_record() {
        let Some(url) = test_url() else {
            eprintln!("TEST_VALKEY_URL not set: Valkey integration test skipped");
            return;
        };
        let v = valkey(&url, &[("HANDOFF_VALID_SECONDS", "0")]).await;
        let (h, secret) = device();
        store(&v, &h, "203.0.113.10").await.unwrap();
        assert_eq!(
            finish(&v, &h, &secret, "203.0.113.10").await,
            Err(HandoffFailure::Expired)
        );
        assert_eq!(v.record(&h.id).await["status"], "expired");
        assert!(v.ttl(&format!("handoff:{}", h.id)).await > 1790);
        assert_eq!(
            finish(&v, &h, &secret, "203.0.113.10").await,
            Err(HandoffFailure::Expired)
        );
        assert!(v.sessions().await.is_empty());
        v.cleanup().await;
        let v = valkey(&url, &[]).await;
        let (h, secret) = device();
        store(&v, &h, "203.0.113.10").await.unwrap();
        assert_eq!(
            finish(&v, &h, &secret, "198.51.100.10").await,
            Err(HandoffFailure::RefusedNetwork)
        );
        assert_eq!(v.record(&h.id).await["status"], "used");
        assert_eq!(
            finish(&v, &h, &secret, "198.51.100.10").await,
            Err(HandoffFailure::Used)
        );
        assert_eq!(
            finish(&v, &h, &secret, "203.0.113.10").await,
            Err(HandoffFailure::Used)
        );
        assert!(v.sessions().await.is_empty());
        v.cleanup().await;
    }
}

mod browser_continuation {
    use super::*;
    use axum::http::HeaderMap;
    use domain::services::browser_handoff::{self, Failure};
    const ORIGIN: &str = "https://auth.asodya.com";
    const CSRF: &str = "source-csrf";
    fn headers(sid: Option<&str>, csrf: Option<&str>) -> HeaderMap {
        let mut h = HeaderMap::new();
        h.insert("origin", ORIGIN.parse().unwrap());
        let mut cookie = String::new();
        if let Some(sid) = sid {
            cookie.push_str(&format!("sid={sid}; "));
        }
        if let Some(csrf) = csrf {
            cookie.push_str(&format!("csrf={csrf}; "));
            h.insert("x-csrf-token", csrf.parse().unwrap());
        }
        h.insert("cookie", cookie.parse().unwrap());
        h
    }
    async fn setup() -> domain::State {
        let mut s = state().await;
        let mut values = (*s.settings.values).clone();
        values.insert("ENVIRONMENT".into(), "production".into());
        s.settings.values = Arc::new(values);
        let at = domain::auth::now();
        s.cache.set("exchange_auth_app:native-a", json!({"session_id":"native-a","native":true,"created_at":at,"last_used_at":at,"user_id":1,"user_uuid_id":"user-a","email":"a@example.test","provider_user_id":"provider-a","access_level":3,"csrf_token":CSRF}), 90000, false).await.unwrap();
        s
    }
    async fn web(s: &domain::State, user: &str) {
        s.cache.set("exchange_auth_app:web", json!({"session_id":"web","user_id":2,"user_uuid_id":user,"email":"browser@example.test","provider_user_id":"provider-web","access_level":3,"csrf_token":"web-csrf"}), 90000, false).await.unwrap();
    }
    async fn create(s: &domain::State) -> (String, Value) {
        let result = browser_handoff::create(s, &headers(Some("native-a"), Some(CSRF)), &json!({"action":"create_browser_handoff","target_app":"certifications","study_id":"prepared-study"})).await.unwrap();
        let url = url::Url::parse(result["launch_url"].as_str().unwrap()).unwrap();
        assert_eq!(url.path(), "/continue");
        assert_eq!(url.query_pairs().count(), 1);
        let (name, handoff) = url.query_pairs().next().unwrap();
        assert_eq!(name, "handoff_id");
        assert!(url.fragment().is_none());
        assert!(!result.to_string().contains("native-a"));
        (handoff.into_owned(), result)
    }
    fn browser_headers(preview: &browser_handoff::Preview, initial: &HeaderMap) -> HeaderMap {
        let mut h = initial.clone();
        h.insert(
            "cookie",
            format!(
                "{}; browser_handoff={}; csrf={}",
                domain::auth::header(initial, "cookie"),
                preview.browser_cookie,
                preview.csrf_cookie
            )
            .parse()
            .unwrap(),
        );
        h.insert("x-csrf-token", preview.csrf_cookie.parse().unwrap());
        h
    }
    fn redeem(id: &str, preview: &browser_handoff::Preview) -> Value {
        json!({"action":"redeem_browser_handoff","handoff_id":id,"browser_state":preview.data["browser_state"]})
    }
    fn failed(error: anyhow::Error, failure: Failure) {
        assert_eq!(error.downcast_ref::<Failure>(), Some(&failure), "{error}");
    }
    async fn mutate(s: &domain::State, id: &str, field: &str, value: Value) {
        let key = format!("handoff:browser:{id}");
        let mut record = s.cache.get(&key, false).await.unwrap().unwrap();
        record[field] = value;
        s.cache.set(&key, record, 1800, false).await.unwrap();
    }

    #[tokio::test]
    async fn anonymous_preview_then_one_use_normal_web_session() {
        let s = setup().await;
        let (id, created) = create(&s).await;
        assert!(created["expires_at"].as_i64().unwrap() <= domain::auth::now() + 300);
        let initial = headers(None, None);
        let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
        assert_eq!(preview.data["account"]["email"], "a@example.test");
        assert_eq!(preview.data["account_mismatch"], false);
        assert!(preview.data["current_account"].is_null());
        for forbidden in ["session_id", "csrf_token", "source_session", "sources"] {
            assert!(preview.data.get(forbidden).is_none());
        }
        let h = browser_headers(&preview, &initial);
        let body = redeem(&id, &preview);
        let result = browser_handoff::redeem(&s, &h, &body).await.unwrap();
        assert_eq!(
            result.target_url,
            "https://certifications.asodya.com/studies/prepared-study"
        );
        let u = result.session.unwrap();
        assert_eq!(u["user_uuid_id"], "user-a");
        assert!(u.get("native").is_none());
        assert!(
            s.cache
                .get(
                    &format!("exchange_auth_app:{}", u["session_id"].as_str().unwrap()),
                    false
                )
                .await
                .unwrap()
                .is_some()
        );
        failed(
            browser_handoff::redeem(&s, &h, &body).await.err().unwrap(),
            Failure::Used,
        );
        assert!(
            s.cache
                .get("exchange_auth_app:native-a", false)
                .await
                .unwrap()
                .is_some()
        );
    }
    #[tokio::test]
    async fn same_account_reuses_browser_session_and_different_account_requires_confirmation() {
        let s = setup().await;
        for (user, mismatch) in [("user-a", false), ("user-b", true)] {
            web(&s, user).await;
            let (id, _) = create(&s).await;
            let initial = headers(Some("web"), Some("web-csrf"));
            let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
            assert_eq!(preview.data["account_mismatch"], mismatch);
            let h = browser_headers(&preview, &initial);
            let mut body = redeem(&id, &preview);
            if mismatch {
                failed(
                    browser_handoff::redeem(&s, &h, &body).await.err().unwrap(),
                    Failure::AccountMismatch,
                );
                assert_eq!(
                    s.cache
                        .get("exchange_auth_app:web", false)
                        .await
                        .unwrap()
                        .unwrap()["user_uuid_id"],
                    "user-b"
                );
                body["confirm_account_switch"] = json!(true);
            }
            let result = browser_handoff::redeem(&s, &h, &body).await.unwrap();
            assert_eq!(result.session.is_some(), mismatch);
            if mismatch {
                assert_eq!(result.session.unwrap()["user_uuid_id"], "user-a");
            }
        }
    }
    #[tokio::test]
    async fn source_session_csrf_native_type_and_request_bindings_are_required() {
        let s = setup().await;
        let body =
            json!({"action":"create_browser_handoff","target_app":"certifications","study_id":"s"});
        failed(
            browser_handoff::create(&s, &headers(None, None), &body)
                .await
                .err()
                .unwrap(),
            Failure::Authentication,
        );
        failed(
            browser_handoff::create(&s, &headers(Some("native-a"), None), &body)
                .await
                .err()
                .unwrap(),
            Failure::Authentication,
        );
        web(&s, "user-a").await;
        failed(
            browser_handoff::create(&s, &headers(Some("web"), Some("web-csrf")), &body)
                .await
                .err()
                .unwrap(),
            Failure::Authentication,
        );
        for (field, value) in [
            ("target_app", json!("reports")),
            ("study_id", json!("../other?owner=attacker")),
            ("user_id", json!(99)),
        ] {
            let mut changed = body.clone();
            changed[field] = value;
            failed(
                browser_handoff::create(&s, &headers(Some("native-a"), Some(CSRF)), &changed)
                    .await
                    .err()
                    .unwrap(),
                Failure::Invalid,
            );
        }
        let (id, _) = create(&s).await;
        let initial = headers(None, None);
        let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
        let good = browser_headers(&preview, &initial);
        let body = redeem(&id, &preview);
        let mut bad = good.clone();
        bad.insert("origin", "https://reports.asodya.com".parse().unwrap());
        failed(
            browser_handoff::redeem(&s, &bad, &body)
                .await
                .err()
                .unwrap(),
            Failure::Origin,
        );
        let mut bad = good.clone();
        bad.remove("x-csrf-token");
        failed(
            browser_handoff::redeem(&s, &bad, &body)
                .await
                .err()
                .unwrap(),
            Failure::Binding,
        );
        let mut bad = good.clone();
        bad.insert(
            "cookie",
            format!("csrf={}", preview.csrf_cookie).parse().unwrap(),
        );
        failed(
            browser_handoff::redeem(&s, &bad, &body)
                .await
                .err()
                .unwrap(),
            Failure::Binding,
        );
        let mut bad_body = body.clone();
        bad_body["browser_state"] = json!(domain::auth::token(32));
        failed(
            browser_handoff::redeem(&s, &good, &bad_body)
                .await
                .err()
                .unwrap(),
            Failure::Binding,
        );
        bad_body = body.clone();
        bad_body["target_app"] = json!("reports");
        failed(
            browser_handoff::redeem(&s, &good, &bad_body)
                .await
                .err()
                .unwrap(),
            Failure::Invalid,
        );
        // Preview may refresh a binding only in the same cookie store.
        failed(
            browser_handoff::preview(&s, &initial, &id)
                .await
                .err()
                .unwrap(),
            Failure::Binding,
        );
        let renewed = browser_handoff::preview(&s, &good, &id).await.unwrap();
        failed(
            browser_handoff::redeem(&s, &good, &body)
                .await
                .err()
                .unwrap(),
            Failure::Binding,
        );
        let h = browser_headers(&renewed, &initial);
        assert!(
            browser_handoff::redeem(&s, &h, &redeem(&id, &renewed))
                .await
                .is_ok()
        );
    }
    #[tokio::test]
    async fn revoked_source_expiry_purpose_and_target_changes_are_refused() {
        let s = setup().await;
        for (field, value, expected) in [
            ("expires_at", json!(0), Failure::Expired),
            ("purpose", json!("native_login"), Failure::Invalid),
            ("target_app", json!("reports"), Failure::Invalid),
            (
                "target_url",
                json!("https://evil.example/"),
                Failure::Invalid,
            ),
            ("user_uuid_id", json!("wrong-user"), Failure::Authentication),
        ] {
            let (id, _) = create(&s).await;
            mutate(&s, &id, field, value).await;
            failed(
                browser_handoff::preview(&s, &headers(None, None), &id)
                    .await
                    .err()
                    .unwrap(),
                expected,
            );
        }
        let (id, _) = create(&s).await;
        let initial = headers(None, None);
        let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
        s.cache.delete("exchange_auth_app:native-a").await.unwrap();
        failed(
            browser_handoff::redeem(
                &s,
                &browser_headers(&preview, &initial),
                &redeem(&id, &preview),
            )
            .await
            .err()
            .unwrap(),
            Failure::Authentication,
        );
    }
    #[tokio::test]
    async fn native_and_bound_browser_cancellation_are_terminal_and_user_scoped() {
        let s = setup().await;
        for from_browser in [false, true] {
            let (id, _) = create(&s).await;
            let initial = headers(None, None);
            let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
            let h = browser_headers(&preview, &initial);
            let mut cancel = json!({"action":"cancel_browser_handoff","handoff_id":id});
            if from_browser {
                cancel["browser_state"] = preview.data["browser_state"].clone();
            }
            let native_headers = headers(Some("native-a"), Some(CSRF));
            browser_handoff::cancel(&s, if from_browser { &h } else { &native_headers }, &cancel)
                .await
                .unwrap();
            failed(
                browser_handoff::redeem(&s, &h, &redeem(&id, &preview))
                    .await
                    .err()
                    .unwrap(),
                Failure::Cancelled,
            );
        }
        let (id, _) = create(&s).await;
        web(&s, "wrong-user").await;
        failed(
            browser_handoff::cancel(
                &s,
                &headers(Some("web"), Some("web-csrf")),
                &json!({"action":"cancel_browser_handoff","handoff_id":id}),
            )
            .await
            .err()
            .unwrap(),
            Failure::Authentication,
        );
    }
    #[tokio::test]
    async fn changed_browser_identity_needs_a_fresh_preview_and_concurrent_redeem_has_one_winner() {
        let s = setup().await;
        let (id, _) = create(&s).await;
        let initial = headers(None, None);
        let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
        let mut h = browser_headers(&preview, &initial);
        web(&s, "user-b").await;
        h.insert(
            "cookie",
            format!(
                "sid=web; browser_handoff={}; csrf={}",
                preview.browser_cookie, preview.csrf_cookie
            )
            .parse()
            .unwrap(),
        );
        failed(
            browser_handoff::redeem(&s, &h, &redeem(&id, &preview))
                .await
                .err()
                .unwrap(),
            Failure::Binding,
        );
        let h = browser_headers(&preview, &initial);
        let body = redeem(&id, &preview);
        let (a, b) = tokio::join!(
            browser_handoff::redeem(&s, &h, &body),
            browser_handoff::redeem(&s, &h, &body)
        );
        assert_ne!(a.is_ok(), b.is_ok());
    }
    #[tokio::test]
    async fn disabled_flag_and_native_artifact_namespace_do_not_fall_through() {
        let mut s = setup().await;
        let (id, _) = create(&s).await;
        let initial = headers(None, None);
        let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
        let mut values = (*s.settings.values).clone();
        values.insert("NATIVE_HANDOFF_ENABLED".into(), "false".into());
        s.settings.values = Arc::new(values);
        failed(
            browser_handoff::preview(&s, &initial, &id)
                .await
                .err()
                .unwrap(),
            Failure::Disabled,
        );
        failed(
            browser_handoff::redeem(
                &s,
                &browser_headers(&preview, &initial),
                &redeem(&id, &preview),
            )
            .await
            .err()
            .unwrap(),
            Failure::Disabled,
        );
        failed(
            browser_handoff::cancel(
                &s,
                &headers(Some("native-a"), Some(CSRF)),
                &json!({"action":"cancel_browser_handoff","handoff_id":id}),
            )
            .await
            .err()
            .unwrap(),
            Failure::Disabled,
        );
        let s = setup().await;
        let native_id = domain::auth::token(32);
        s.cache
            .set(
                &format!("handoff:{native_id}"),
                json!({"status":"done","purpose":"native_login"}),
                1800,
                false,
            )
            .await
            .unwrap();
        failed(
            browser_handoff::preview(&s, &initial, &native_id)
                .await
                .err()
                .unwrap(),
            Failure::Expired,
        );
        // The delivered native Finish still reads only its own namespace.
        let (browser_id, _) = create(&s).await;
        let result = domain::auth::finish_handoff(
            &s,
            &json!({"app":"annotations","handoff_id":browser_id,"secret":domain::auth::token(32)}),
            &HeaderMap::new(),
            "127.0.0.1",
        )
        .await
        .err()
        .unwrap();
        assert_eq!(
            result.downcast_ref::<domain::auth::HandoffFailure>(),
            Some(&domain::auth::HandoffFailure::NotFinished)
        );
    }

    #[tokio::test]
    async fn browser_continuation_valkey_atomic_redeem_and_original_ttl() {
        let Ok(url) = std::env::var("TEST_VALKEY_URL") else {
            return;
        };
        let parsed = url::Url::parse(&url).unwrap();
        assert_eq!(parsed.host_str(), Some("127.0.0.1"));
        assert!(
            parsed
                .port()
                .is_some_and(|port| port >= 1024 && port != 6379)
        );
        let mut s = setup().await;
        let source = s
            .cache
            .get("exchange_auth_app:native-a", false)
            .await
            .unwrap()
            .unwrap();
        let namespace = format!("test65:{}:", domain::auth::token(12));
        s.cache = dal::cache::Cache::new(&url, &namespace).await.unwrap();
        s.cache
            .set("exchange_auth_app:native-a", source, 90000, true)
            .await
            .unwrap();
        let mut raw = redis::Client::open(url)
            .unwrap()
            .get_connection_manager()
            .await
            .unwrap();
        let (id, _) = create(&s).await;
        let handoff_key = format!("{namespace}handoff:browser:{id}");
        let before: i64 = redis::cmd("TTL")
            .arg(&handoff_key)
            .query_async(&mut raw)
            .await
            .unwrap();
        assert!((1790..=1800).contains(&before));
        let initial = headers(None, None);
        let preview = browser_handoff::preview(&s, &initial, &id).await.unwrap();
        let h = browser_headers(&preview, &initial);
        let body = redeem(&id, &preview);
        let mut tasks = tokio::task::JoinSet::new();
        for _ in 0..16 {
            let (s, h, body) = (s.clone(), h.clone(), body.clone());
            tasks.spawn(async move { browser_handoff::redeem(&s, &h, &body).await });
        }
        let mut winners = 0;
        while let Some(result) = tasks.join_next().await {
            match result.unwrap() {
                Ok(_) => winners += 1,
                Err(error) => failed(error, Failure::Used),
            }
        }
        assert_eq!(winners, 1);
        let after: i64 = redis::cmd("TTL")
            .arg(&handoff_key)
            .query_async(&mut raw)
            .await
            .unwrap();
        assert!(after <= before && after >= before - 5);
        let keys: Vec<String> = redis::cmd("KEYS")
            .arg(format!("{namespace}exchange_auth_app:*"))
            .query_async(&mut raw)
            .await
            .unwrap();
        assert_eq!(keys.len(), 2, "one native and one new browser session");
        let record = s
            .cache
            .get(&format!("handoff:browser:{id}"), false)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(record["status"], "used");
        // Remove only this test's unique namespace; never flush the instance.
        let keys: Vec<String> = redis::cmd("KEYS")
            .arg(format!("{namespace}*"))
            .query_async(&mut raw)
            .await
            .unwrap();
        let _: u64 = redis::cmd("DEL")
            .arg(keys)
            .query_async(&mut raw)
            .await
            .unwrap();
    }

    async fn request(
        s: domain::State,
        method: &str,
        path: &str,
        body: Value,
        h: &HeaderMap,
    ) -> (StatusCode, HeaderMap, Value) {
        let mut req = Request::builder()
            .method(method)
            .uri(path)
            .header("host", "api.asodya.com")
            .header("x-forwarded-proto", "https");
        for (k, v) in h {
            req = req.header(k, v);
        }
        let mut req = req
            .body(Body::from(serde_json::to_vec(&body).unwrap()))
            .unwrap();
        req.extensions_mut().insert(ConnectInfo(
            "127.0.0.1:5000".parse::<std::net::SocketAddr>().unwrap(),
        ));
        let r = presentation::router(s).oneshot(req).await.unwrap();
        let status = r.status();
        let headers = r.headers().clone();
        let body: Value =
            serde_json::from_slice(&to_bytes(r.into_body(), 65536).await.unwrap()).unwrap();
        (status, headers, body)
    }
    #[tokio::test]
    async fn http_preview_sets_binding_cookies_and_redeem_sets_only_web_credentials_in_cookies() {
        let s = setup().await;
        let (status,_,created)=request(s.clone(),"POST","/apps/api/v1/exchange",json!({"action":"create_browser_handoff","target_app":"certifications","study_id":"study"}),&headers(Some("native-a"),Some(CSRF))).await;
        assert_eq!(status, 200);
        let launch = url::Url::parse(created["data"]["launch_url"].as_str().unwrap()).unwrap();
        let query = launch.query().unwrap();
        let path = format!("/apps/api/v1/exchange?{query}");
        let (status, response_headers, preview) =
            request(s.clone(), "GET", &path, Value::Null, &headers(None, None)).await;
        assert_eq!(status, 200, "{preview}");
        assert_eq!(response_headers["cache-control"], "no-store");
        assert_eq!(response_headers["referrer-policy"], "no-referrer");
        let cookies: Vec<&str> = response_headers
            .get_all("set-cookie")
            .iter()
            .map(|v| v.to_str().unwrap())
            .collect();
        assert!(cookies.iter().any(|c| c.starts_with("browser_handoff=")
            && c.contains("HttpOnly")
            && c.contains("Secure")));
        assert!(
            cookies
                .iter()
                .any(|c| c.starts_with("csrf=") && !c.contains("HttpOnly"))
        );
        let mut h = headers(None, None);
        let cookie = cookies
            .iter()
            .map(|c| c.split(';').next().unwrap())
            .collect::<Vec<_>>()
            .join("; ");
        h.insert("cookie", cookie.parse().unwrap());
        let csrf = domain::auth::cookie(&h, "csrf").unwrap();
        h.insert("x-csrf-token", csrf.parse().unwrap());
        let id = launch.query_pairs().next().unwrap().1.into_owned();
        let (status,response_headers,result)=request(s,"POST","/apps/api/v1/exchange",json!({"action":"redeem_browser_handoff","handoff_id":id,"browser_state":preview["data"]["browser_state"]}),&h).await;
        assert_eq!(status, 200, "{result}");
        assert_eq!(
            result["data"]["target_url"],
            "https://certifications.asodya.com/studies/study"
        );
        assert_eq!(result["data"].as_object().unwrap().len(), 1);
        let cookies: Vec<&str> = response_headers
            .get_all("set-cookie")
            .iter()
            .map(|v| v.to_str().unwrap())
            .collect();
        assert!(
            cookies
                .iter()
                .any(|c| c.starts_with("sid=") && c.contains("HttpOnly"))
        );
        assert_eq!(response_headers["cache-control"], "no-store");
    }
}

mod central_plans {
    use super::*;
    use domain::{
        models::plans::{Membership, Update},
        services::plans,
    };
    const PUBLIC: &str = "/apps/api/v1/plans?app_id=certifications";
    const ADMIN: &str = "/apps/api/v1/admin";
    const ADMIN_HEADERS: &[(&str, &str)] = &[("authorization", "test-admin")];
    async fn setup() -> domain::State {
        let s = state().await;
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        sqlx::raw_sql(&include_str!("../migrations/001_app_catalog.sql").replace("public.", ""))
            .execute(pool)
            .await
            .unwrap();
        let schema = include_str!("../migrations/004_app_plans.sql").replace("public.", "");
        sqlx::raw_sql(&schema).execute(pool).await.unwrap();
        sqlx::raw_sql(&schema).execute(pool).await.unwrap();
        assert_eq!(
            sqlx::query_scalar::<_, i64>("SELECT count(*) FROM app_plans")
                .fetch_one(pool)
                .await
                .unwrap(),
            0
        );
        sqlx::query("INSERT INTO defaultdb_app(id,name,is_active) VALUES('certifications','Certifications',true),('annotations','Annotations',true),('inactive','Inactive',false)").execute(pool).await.unwrap();
        s
    }
    fn plan(app: &str, code: &str, active: bool) -> Value {
        json!({"app_id":app,"code":code,"name":"Public display name","description":"Description","is_active":active})
    }
    async fn create(s: &domain::State, kind: &str, body: Value) -> Value {
        let (status, result) = call(
            s.clone(),
            "POST",
            &format!("{ADMIN}/{kind}"),
            body,
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(status, 201, "{result}");
        result["data"].clone()
    }
    #[tokio::test]
    async fn public_returns_only_active_free_plans_of_active_app_and_live_features() {
        let s = setup().await;
        assert_eq!(
            call(s.clone(), "GET", PUBLIC, json!({}), &[]).await.1["data"],
            json!([])
        );
        let free = create(&s, "plans", plan("certifications", "free", true)).await;
        create(&s, "plans", plan("certifications", "future", false)).await;
        create(&s, "plans", plan("annotations", "free", true)).await;
        create(&s, "plans", plan("inactive", "free", true)).await;
        let feature = create(&s, "features", plan("certifications", "search", true)).await;
        let hidden = create(&s, "features", plan("certifications", "draft", false)).await;
        for feature in [&feature, &hidden] {
            create(
                &s,
                "plan-features",
                json!({"plan_id":free["id"],"feature_id":feature["id"]}),
            )
            .await;
        }
        let (status, result) = call(s.clone(), "GET", PUBLIC, json!({}), &[]).await;
        assert_eq!(status, 200);
        assert_eq!(result["data"].as_array().unwrap().len(), 1);
        assert_eq!(result["data"][0]["code"], "free");
        assert_eq!(result["data"][0]["name"], "Public display name");
        assert_eq!(result["data"][0]["features"].as_array().unwrap().len(), 1);
        assert_eq!(result["data"][0]["features"][0]["id"], feature["id"]);
        let path = format!("{ADMIN}/features/{}", feature["id"].as_str().unwrap());
        assert_eq!(
            call(
                s.clone(),
                "PATCH",
                &path,
                json!({"is_active":false}),
                ADMIN_HEADERS
            )
            .await
            .0,
            200
        );
        assert_eq!(
            call(s.clone(), "GET", PUBLIC, json!({}), &[]).await.1["data"][0]["features"],
            json!([])
        );
        let path = format!("{ADMIN}/plans/{}", free["id"].as_str().unwrap());
        assert_eq!(
            call(
                s.clone(),
                "PATCH",
                &path,
                json!({"is_active":false}),
                ADMIN_HEADERS
            )
            .await
            .0,
            200
        );
        assert_eq!(
            call(s.clone(), "GET", PUBLIC, json!({}), &[]).await.1["data"],
            json!([])
        );
        assert_eq!(
            call(
                s.clone(),
                "GET",
                "/apps/api/v1/plans?app_id=inactive",
                json!({}),
                &[]
            )
            .await
            .1["data"],
            json!([])
        );
        let (_, admin) = call(
            s,
            "GET",
            &format!("{ADMIN}/plans?app_id=certifications"),
            json!({}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(admin["data"].as_array().unwrap().len(), 2);
    }
    #[tokio::test]
    async fn only_stable_free_code_can_be_active_and_invalid_authority_fields_are_rejected() {
        let s = setup().await;
        let (status, error) = call(
            s.clone(),
            "POST",
            &format!("{ADMIN}/plans"),
            plan("certifications", "paid", true),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(status, 400);
        assert_eq!(error["data"]["code"], "ONLY_FREE_PLAN_ACTIVE");
        let future = create(&s, "plans", plan("certifications", "future", false)).await;
        let path = format!("{ADMIN}/plans/{}", future["id"].as_str().unwrap());
        assert_eq!(
            call(
                s.clone(),
                "PATCH",
                &path,
                json!({"is_active":true}),
                ADMIN_HEADERS
            )
            .await
            .1["data"]["code"],
            "ONLY_FREE_PLAN_ACTIVE"
        );
        for payload in [
            json!({"app_id":"annotations"}),
            json!({"code":"free"}),
            json!({"owner_id":"someone"}),
            json!({}),
            json!({"name":"   "}),
        ] {
            assert_eq!(
                call(s.clone(), "PATCH", &path, payload, ADMIN_HEADERS)
                    .await
                    .0,
                400
            );
        }
        let mut claimed = plan("certifications", "free", true);
        claimed["access_level"] = json!(1);
        assert_eq!(
            call(
                s.clone(),
                "POST",
                &format!("{ADMIN}/plans"),
                claimed,
                ADMIN_HEADERS
            )
            .await
            .0,
            400
        );
        let unknown = call(
            s.clone(),
            "POST",
            &format!("{ADMIN}/plans"),
            plan("missing", "free", true),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(unknown.0, 404);
        assert_eq!(unknown.1["data"]["code"], "PLAN_APP_NOT_FOUND");
        let free = create(&s, "plans", plan("certifications", "free", true)).await;
        assert_eq!(
            call(
                s.clone(),
                "POST",
                &format!("{ADMIN}/plans"),
                plan("certifications", "free", true),
                ADMIN_HEADERS
            )
            .await
            .0,
            409
        );
        let path = format!("{ADMIN}/plans/{}", free["id"].as_str().unwrap());
        let (_, renamed) = call(
            s.clone(),
            "PATCH",
            &path,
            json!({"name":"Gratuito"}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(renamed["data"]["code"], "free");
        assert_eq!(renamed["data"]["is_active"], true);
        for query in [
            "",
            "?app_id=",
            "?app_id=certifications&app_id=annotations",
            "?app_id=certifications&owner_id=other",
        ] {
            assert_eq!(
                call(
                    s.clone(),
                    "GET",
                    &format!("/apps/api/v1/plans{query}"),
                    json!({}),
                    &[]
                )
                .await
                .0,
                400
            );
        }
    }
    #[tokio::test]
    async fn cross_app_memberships_are_refused_and_deletes_remove_only_related_rows() {
        let s = setup().await;
        let free = create(&s, "plans", plan("certifications", "free", true)).await;
        let local = create(&s, "features", plan("certifications", "search", true)).await;
        let other = create(&s, "features", plan("annotations", "search", true)).await;
        let pair = json!({"plan_id":free["id"],"feature_id":local["id"]});
        let path = format!("{ADMIN}/plan-features");
        let (status, error) = call(
            s.clone(),
            "POST",
            &path,
            json!({"plan_id":free["id"],"feature_id":other["id"]}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(status, 400);
        assert_eq!(error["data"]["code"], "PLAN_FEATURE_APP_MISMATCH");
        create(&s, "plan-features", pair.clone()).await;
        assert_eq!(
            call(s.clone(), "POST", &path, pair, ADMIN_HEADERS).await.0,
            409
        );
        let pair_path = format!(
            "{ADMIN}/plan-features/{}/{}",
            free["id"].as_str().unwrap(),
            local["id"].as_str().unwrap()
        );
        assert_eq!(
            call(s.clone(), "DELETE", &pair_path, json!({}), ADMIN_HEADERS)
                .await
                .0,
            200
        );
        assert_eq!(
            call(s.clone(), "DELETE", &pair_path, json!({}), ADMIN_HEADERS)
                .await
                .0,
            404
        );
        create(
            &s,
            "plan-features",
            json!({"plan_id":free["id"],"feature_id":local["id"]}),
        )
        .await;
        let feature_path = format!("{ADMIN}/features/{}", local["id"].as_str().unwrap());
        assert_eq!(
            call(s.clone(), "DELETE", &feature_path, json!({}), ADMIN_HEADERS)
                .await
                .0,
            200
        );
        assert_eq!(
            call(s.clone(), "GET", PUBLIC, json!({}), &[]).await.1["data"][0]["features"],
            json!([])
        );
        let plan_path = format!("{ADMIN}/plans/{}", free["id"].as_str().unwrap());
        assert_eq!(
            call(s.clone(), "DELETE", &plan_path, json!({}), ADMIN_HEADERS)
                .await
                .0,
            200
        );
        assert_eq!(
            call(s.clone(), "GET", PUBLIC, json!({}), &[]).await.1["data"],
            json!([])
        );
        let (_, result) = call(
            s,
            "GET",
            &format!("{ADMIN}/features?app_id=annotations"),
            json!({}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(result["data"][0]["id"], other["id"]);
    }
    #[tokio::test]
    async fn central_admin_level_and_mutation_csrf_precede_body_validation() {
        let s = setup().await;
        s.cache
            .set(
                "exchange_auth_app:normal",
                json!({"session_id":"normal","access_level":3,"csrf_token":"c"}),
                60,
                false,
            )
            .await
            .unwrap();
        s.cache
            .set(
                "exchange_auth_app:admin",
                json!({"session_id":"admin","access_level":1,"csrf_token":"c"}),
                60,
                false,
            )
            .await
            .unwrap();
        let normal = &[("cookie", "sid=normal; csrf=c"), ("x-csrf-token", "c")];
        for (method, path) in [
            ("GET", format!("{ADMIN}/plans?app_id=certifications")),
            ("POST", format!("{ADMIN}/plans")),
            ("PATCH", format!("{ADMIN}/plans/invalid")),
            ("DELETE", format!("{ADMIN}/features/invalid")),
            ("POST", format!("{ADMIN}/plan-features")),
        ] {
            assert_eq!(
                call(s.clone(), method, &path, json!({"access_level":1}), normal)
                    .await
                    .0,
                403
            );
            assert_eq!(call(s.clone(), method, &path, json!({}), &[]).await.0, 403);
        }
        let path = format!("{ADMIN}/plans");
        assert_eq!(
            call(
                s.clone(),
                "POST",
                &path,
                plan("certifications", "free", true),
                &[("cookie", "sid=admin; csrf=c")]
            )
            .await
            .0,
            403
        );
        assert_eq!(
            call(
                s.clone(),
                "POST",
                &path,
                plan("certifications", "free", true),
                &[("cookie", "sid=admin; csrf=c"), ("x-csrf-token", "c")]
            )
            .await
            .0,
            201
        );
        assert_eq!(call(s, "GET", PUBLIC, json!({}), &[]).await.0, 200);
    }
    #[tokio::test]
    async fn unavailable_schema_does_not_create_or_seed_it_at_request_time() {
        let s = state().await;
        let (status, error) = call(s.clone(), "GET", PUBLIC, json!({}), &[]).await;
        assert_eq!(status, 503);
        assert_eq!(error["data"]["code"], "PLAN_SERVICE_UNAVAILABLE");
        assert!(!error.to_string().contains("SELECT"));
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        assert_eq!(
            sqlx::query_scalar::<_, i64>(
                "SELECT count(*) FROM sqlite_master WHERE name='app_plans'"
            )
            .fetch_one(pool)
            .await
            .unwrap(),
            0
        );
    }
    #[tokio::test]
    async fn postgres_plans_schema_and_queries_on_disposable_test_database() {
        let Ok(connection) = std::env::var("TEST_PLANS_PG_URL") else {
            return;
        };
        let parsed = url::Url::parse(&connection).unwrap();
        assert_eq!(parsed.host_str(), Some("127.0.0.1"));
        assert!(
            parsed
                .port()
                .is_some_and(|port| port >= 1024 && port != 5432)
        );
        assert_eq!(
            parsed.path(),
            "/gateway66_test",
            "disposable named test database only"
        );
        let pool = sqlx::PgPool::connect(&connection).await.unwrap();
        for _ in 0..2 {
            sqlx::raw_sql(include_str!("../migrations/001_app_catalog.sql"))
                .execute(&pool)
                .await
                .unwrap();
            sqlx::raw_sql(include_str!("../migrations/004_app_plans.sql"))
                .execute(&pool)
                .await
                .unwrap();
        }
        let app = format!("plan-test-{}", uuid::Uuid::new_v4().simple());
        sqlx::query("INSERT INTO defaultdb_app(id,name,is_active) VALUES($1,'Test',true)")
            .bind(&app)
            .execute(&pool)
            .await
            .unwrap();
        let mut s = state().await;
        s.db = dal::database::Database::Pg(pool.clone());
        let free = plans::create_plan(
            &s,
            serde_json::from_value(plan(&app, "free", true)).unwrap(),
        )
        .await
        .unwrap();
        let feature = plans::create_feature(
            &s,
            serde_json::from_value(plan(&app, "search", true)).unwrap(),
        )
        .await
        .unwrap();
        plans::attach(
            &s,
            &Membership {
                plan_id: free.id.clone(),
                feature_id: feature.id.clone(),
            },
        )
        .await
        .unwrap();
        let result = plans::plans(&s, &app, true).await.unwrap();
        assert_eq!(result.len(), 1);
        assert_eq!(result[0].features[0].id, feature.id);
        assert!(sqlx::query("INSERT INTO app_plans(id,app_id,code,name,is_active) VALUES('bad',$1,'paid','Paid',true)").bind(&app).execute(&pool).await.is_err());
        plans::update_plan(
            &s,
            &free.id,
            Update {
                is_active: Some(false),
                ..Default::default()
            },
        )
        .await
        .unwrap();
        assert!(plans::plans(&s, &app, true).await.unwrap().is_empty());
        plans::delete_feature(&s, &feature.id).await.unwrap();
        plans::delete_plan(&s, &free.id).await.unwrap();
        sqlx::query("DELETE FROM defaultdb_app WHERE id=$1")
            .bind(&app)
            .execute(&pool)
            .await
            .unwrap();
        let forbidden:i64=sqlx::query_scalar("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('app_plans','app_features','plan_features') AND (data_type IN ('json','jsonb','ARRAY'))").fetch_one(&pool).await.unwrap();
        assert_eq!(forbidden, 0);
    }
}
mod central_waitlist {
    use super::*;
    use domain::{
        models::waitlist::{Filter, Join, StatusUpdate},
        services::waitlist,
    };
    const PUBLIC: &str = "/apps/api/v1/waitlist";
    const ADMIN: &str = "/apps/api/v1/admin/waitlist";
    const ADMIN_HEADERS: &[(&str, &str)] = &[("authorization", "test-admin")];
    const PLAN: &str = "11111111-1111-4111-8111-111111111111";
    async fn setup() -> domain::State {
        let s = state().await;
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        sqlx::query("CREATE UNIQUE INDEX user_uuid_fixture ON defaultdb_user(uuid_id)")
            .execute(pool)
            .await
            .unwrap();
        for schema in [
            include_str!("../migrations/001_app_catalog.sql"),
            include_str!("../migrations/004_app_plans.sql"),
            include_str!("../migrations/005_central_waitlist.sql"),
            include_str!("../migrations/005_central_waitlist.sql"),
        ] {
            sqlx::raw_sql(&schema.replace("public.", ""))
                .execute(pool)
                .await
                .unwrap();
        }
        sqlx::raw_sql(&format!("INSERT INTO defaultdb_app(id,name,is_active) VALUES('certifications','Certifications',true),('annotations','Annotations',true),('inactive','Inactive',false);
            INSERT INTO app_plans(id,app_id,code,name,is_active) VALUES('{PLAN}','certifications','free','Free',true),('other-plan','annotations','pro','Pro',false),('future','certifications','pro','Pro',false);
            INSERT INTO app_features(id,app_id,code,name) VALUES('feature','certifications','search','Search');
            INSERT INTO defaultdb_user(id,uuid_id,email,access_level,is_active) VALUES(1,'user-1','person@example.test',3,1);")).execute(pool).await.unwrap();
        s
    }
    fn join(app: &str, kind: &str, target: &str, email: &str) -> Value {
        json!({"app_id":app,"target_type":kind,"target":target,"email":email})
    }
    async fn post(
        s: &domain::State,
        body: Value,
        ip: &str,
        extra: &[(&str, &str)],
    ) -> (StatusCode, Value) {
        let mut headers = vec![("cf-connecting-ip", ip)];
        headers.extend_from_slice(extra);
        call(s.clone(), "POST", PUBLIC, body, &headers).await
    }
    async fn rows(s: &domain::State) -> Vec<(String, String, Option<String>)> {
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        sqlx::query_as(
            "SELECT email,target_type,user_id FROM app_waitlist_entries ORDER BY email,target_type",
        )
        .fetch_all(pool)
        .await
        .unwrap()
    }
    #[tokio::test]
    async fn public_join_is_duplicate_safe_and_never_hints_at_existing_emails() {
        let s = setup().await;
        let first = post(
            &s,
            join("certifications", "plan", "free", "Person@Example.test"),
            "192.0.2.1",
            &[],
        )
        .await;
        assert_eq!(first.0, 202, "{}", first.1);
        let again = post(
            &s,
            join("certifications", "plan", "free", " person@example.TEST "),
            "192.0.2.2",
            &[],
        )
        .await;
        assert_eq!((again.0, &again.1), (first.0, &first.1));
        assert_eq!(
            first.1,
            json!({"message":"Waitlist request received.","data":null})
        );
        let other = post(
            &s,
            join("certifications", "plan", "free", "new@example.test"),
            "192.0.2.3",
            &[],
        )
        .await;
        assert_eq!((other.0, &other.1), (first.0, &first.1));
        for (body, ip) in [
            (
                join("certifications", "plan", "pro", "other@example.test"),
                "192.0.2.4",
            ),
            (
                join("certifications", "feature", "search", "person@example.test"),
                "192.0.2.5",
            ),
            (
                join(
                    "certifications",
                    "interest",
                    "launch-news",
                    "other@example.test",
                ),
                "192.0.2.6",
            ),
        ] {
            assert_eq!(post(&s, body, ip, &[]).await.0, 202);
        }
        let stored = rows(&s).await;
        assert_eq!(stored.len(), 5);
        assert_eq!(
            stored
                .iter()
                .filter(|r| r.0 == "person@example.test")
                .count(),
            2
        );
        assert!(stored.iter().all(|r| r.2.is_none()));
        let cache_header = Request::builder()
            .method("POST")
            .uri(PUBLIC)
            .header("x-forwarded-for", "192.0.2.7")
            .body(Body::from(
                join("certifications", "plan", "free", "z@example.test").to_string(),
            ))
            .map(|mut r| {
                r.extensions_mut().insert(ConnectInfo(
                    "127.0.0.1:5000".parse::<std::net::SocketAddr>().unwrap(),
                ));
                r
            })
            .unwrap();
        let r = presentation::router(s.clone())
            .oneshot(cache_header)
            .await
            .unwrap();
        assert_eq!(r.headers()["cache-control"], "no-store");
    }
    #[tokio::test]
    async fn public_join_validates_app_target_and_fields() {
        let s = setup().await;
        let cases = [
            (
                join("missing", "plan", "free", "a@example.test"),
                404,
                "WAITLIST_APP_NOT_FOUND",
            ),
            (
                join("inactive", "interest", "news", "a@example.test"),
                404,
                "WAITLIST_APP_NOT_FOUND",
            ),
            (
                join("certifications", "plan", "missing", "a@example.test"),
                404,
                "WAITLIST_TARGET_NOT_FOUND",
            ),
            (
                join("annotations", "plan", "free", "a@example.test"),
                404,
                "WAITLIST_TARGET_NOT_FOUND",
            ),
            (
                join("annotations", "feature", "search", "a@example.test"),
                404,
                "WAITLIST_TARGET_NOT_FOUND",
            ),
            (
                join("certifications", "plan", "free", "not-an-email"),
                400,
                "INVALID_WAITLIST_DATA",
            ),
            (
                join("certifications", "billing", "free", "a@example.test"),
                400,
                "INVALID_WAITLIST_DATA",
            ),
            (
                join("certifications", "interest", "Bad Code", "a@example.test"),
                400,
                "INVALID_WAITLIST_DATA",
            ),
            (
                json!({"app_id":"certifications","target_type":"plan","target":"free","email":"a@example.test","user_id":"user-1"}),
                400,
                "INVALID_WAITLIST_DATA",
            ),
            (
                json!({"app_id":"certifications","email":"a@example.test"}),
                400,
                "INVALID_WAITLIST_DATA",
            ),
        ];
        for (n, (mut body, status, code)) in cases.into_iter().enumerate() {
            if body["email"] == "a@example.test" {
                body["email"] = json!(format!("a{n}@example.test"));
            }
            let (got, result) = post(&s, body, &format!("198.51.100.{n}"), &[]).await;
            assert_eq!(
                (got.as_u16(), result["data"]["code"].as_str()),
                (status, Some(code)),
                "{result}"
            );
        }
        assert!(rows(&s).await.is_empty());
        assert_eq!(call(s.clone(), "GET", PUBLIC, json!({}), &[]).await.0, 405);
    }
    #[tokio::test]
    async fn public_join_uses_the_gateway_rate_limit_per_email_and_ip() {
        let s = setup().await;
        for n in 0..3 {
            let ip = format!("203.0.113.{n}");
            assert_eq!(
                post(
                    &s,
                    join("certifications", "interest", "news", "busy@example.test"),
                    &ip,
                    &[]
                )
                .await
                .0,
                202
            );
        }
        let (status, result) = post(
            &s,
            join("certifications", "interest", "news", "busy@example.test"),
            "203.0.113.9",
            &[],
        )
        .await;
        assert_eq!(status, 429);
        assert_eq!(result["data"]["code"], "WAITLIST_RATE_LIMITED");
        for n in 0..5 {
            let email = format!("ip{n}@example.test");
            assert_eq!(
                post(
                    &s,
                    join("certifications", "interest", "news", &email),
                    "203.0.113.50",
                    &[]
                )
                .await
                .0,
                202
            );
        }
        assert_eq!(
            post(
                &s,
                join("certifications", "interest", "news", "ip9@example.test"),
                "203.0.113.50",
                &[]
            )
            .await
            .0,
            429
        );
    }
    /// Sends a public join from a chosen socket peer, so the trusted client IP rule is tested.
    async fn post_from(
        s: &domain::State,
        email: &str,
        peer: &str,
        headers: &[(&str, &str)],
    ) -> (StatusCode, Value) {
        let mut req = Request::builder().method("POST").uri(PUBLIC);
        for (k, v) in headers {
            req = req.header(*k, *v)
        }
        let mut req = req
            .body(Body::from(
                join("certifications", "interest", "news", email).to_string(),
            ))
            .unwrap();
        req.extensions_mut()
            .insert(ConnectInfo(std::net::SocketAddr::new(
                peer.parse().unwrap(),
                5000,
            )));
        let r = presentation::router(s.clone()).oneshot(req).await.unwrap();
        let status = r.status();
        let b = to_bytes(r.into_body(), 65536).await.unwrap();
        (status, serde_json::from_slice(&b).unwrap_or(Value::Null))
    }
    #[tokio::test]
    async fn direct_client_cannot_escape_the_ip_limit_with_x_forwarded_for() {
        let s = setup().await;
        for n in 0..5 {
            let forwarded = format!("192.0.2.{n}");
            let (status, body) = post_from(
                &s,
                &format!("direct{n}@example.test"),
                "198.51.100.20",
                &[("x-forwarded-for", forwarded.as_str())],
            )
            .await;
            assert_eq!(status, 202, "{body}");
        }
        let (status, body) = post_from(
            &s,
            "direct9@example.test",
            "198.51.100.20",
            &[("x-forwarded-for", "192.0.2.99")],
        )
        .await;
        assert_eq!(status, 429);
        assert_eq!(body["data"]["code"], "WAITLIST_RATE_LIMITED");
        // The same spoofed header from the local tunnel is ignored too.
        for n in 0..5 {
            let forwarded = format!("192.0.2.{}", 100 + n);
            let email = format!("tunnel{n}@example.test");
            let headers = [("x-forwarded-for", forwarded.as_str())];
            assert_eq!(post_from(&s, &email, "127.0.0.1", &headers).await.0, 202);
        }
        let headers = [("x-forwarded-for", "192.0.2.200")];
        let blocked = post_from(&s, "tunnel9@example.test", "127.0.0.1", &headers).await;
        assert_eq!(blocked.0, 429);
    }
    #[tokio::test]
    async fn loopback_proxy_keys_the_limit_by_cf_connecting_ip() {
        let s = setup().await;
        for n in 0..5 {
            let email = format!("proxied{n}@example.test");
            let headers = [("cf-connecting-ip", "203.0.113.60")];
            assert_eq!(post_from(&s, &email, "127.0.0.1", &headers).await.0, 202);
        }
        let headers = [("cf-connecting-ip", "203.0.113.60")];
        let blocked = post_from(&s, "proxied9@example.test", "127.0.0.1", &headers).await;
        assert_eq!(blocked.0, 429);
        assert_eq!(blocked.1["data"]["code"], "WAITLIST_RATE_LIMITED");
        // Another client behind the same tunnel has its own key.
        let headers = [("cf-connecting-ip", "203.0.113.61")];
        let other = post_from(&s, "other-client@example.test", "127.0.0.1", &headers).await;
        assert_eq!(other.0, 202, "{}", other.1);
        let ipv6 = [("cf-connecting-ip", "2001:db8::61")];
        let other = post_from(&s, "ipv6-client@example.test", "::1", &ipv6).await;
        assert_eq!(other.0, 202, "{}", other.1);
    }
    #[tokio::test]
    async fn non_loopback_peer_is_keyed_by_its_socket_address() {
        let s = setup().await;
        for n in 0..5 {
            let claimed = format!("203.0.113.{}", 70 + n);
            let email = format!("remote{n}@example.test");
            let headers = [("cf-connecting-ip", claimed.as_str())];
            let (status, body) = post_from(&s, &email, "198.51.100.30", &headers).await;
            assert_eq!(status, 202, "{body}");
        }
        let headers = [("cf-connecting-ip", "203.0.113.99")];
        let blocked = post_from(&s, "remote9@example.test", "198.51.100.30", &headers).await;
        assert_eq!(blocked.0, 429);
        assert_eq!(blocked.1["data"]["code"], "WAITLIST_RATE_LIMITED");
        // A different socket peer still has its own budget.
        let other = post_from(&s, "remote-other@example.test", "198.51.100.31", &headers).await;
        assert_eq!(other.0, 202, "{}", other.1);
    }
    #[tokio::test]
    async fn sign_in_rate_key_uses_the_trusted_client_ip() {
        use axum::http::HeaderMap;
        let s = state().await;
        let mut spoofed = HeaderMap::new();
        for n in 0..5 {
            spoofed.insert("x-forwarded-for", format!("192.0.2.{n}").parse().unwrap());
            domain::auth::rate(&s, &spoofed, "198.51.100.40", "login", None, false)
                .await
                .unwrap();
        }
        spoofed.insert("x-forwarded-for", "192.0.2.77".parse().unwrap());
        let error = domain::auth::rate(&s, &spoofed, "198.51.100.40", "login", None, false)
            .await
            .unwrap_err();
        assert!(error.to_string().starts_with("Too many login"));
        let mut tunnel = HeaderMap::new();
        tunnel.insert("cf-connecting-ip", "203.0.113.80".parse().unwrap());
        domain::auth::rate(&s, &tunnel, "127.0.0.1", "login", None, false)
            .await
            .unwrap();
        assert_eq!(
            domain::auth::request_ip(&tunnel, "127.0.0.1".parse().unwrap()).to_string(),
            "203.0.113.80"
        );
        assert_eq!(
            domain::auth::request_ip(&tunnel, "198.51.100.40".parse().unwrap()).to_string(),
            "198.51.100.40"
        );
        assert_eq!(
            domain::auth::request_ip(&spoofed, "127.0.0.1".parse().unwrap()).to_string(),
            "127.0.0.1"
        );
    }
    #[tokio::test]
    async fn session_user_is_linked_only_to_their_own_email() {
        let s = setup().await;
        s.cache
            .set(
                "exchange_auth_app:person",
                json!({"user_uuid_id":"user-1","email":"Person@example.test","access_level":3,"csrf_token":"c"}),
                60,
                false,
            )
            .await
            .unwrap();
        let session = [("cookie", "sid=person")];
        assert_eq!(
            post(
                &s,
                join("certifications", "interest", "news", "person@example.test"),
                "192.0.2.10",
                &[]
            )
            .await
            .0,
            202
        );
        assert_eq!(
            post(
                &s,
                join("certifications", "interest", "news", "person@example.test"),
                "192.0.2.11",
                &session
            )
            .await
            .0,
            202
        );
        assert_eq!(
            post(
                &s,
                join("certifications", "plan", "free", "someone@example.test"),
                "192.0.2.12",
                &session
            )
            .await
            .0,
            202
        );
        assert_eq!(
            post(
                &s,
                join("certifications", "plan", "free", "person@example.test"),
                "192.0.2.13",
                &session
            )
            .await
            .0,
            202
        );
        let stored = rows(&s).await;
        assert_eq!(stored.len(), 3);
        for (email, _, user) in stored {
            assert_eq!(user.is_some(), email == "person@example.test", "{email}");
        }
    }
    #[tokio::test]
    async fn admin_lists_with_bounded_filters_and_updates_status() {
        let s = setup().await;
        for (n, body) in [
            join("certifications", "plan", "free", "a@example.test"),
            join("certifications", "plan", "free", "b@example.test"),
            join("certifications", "feature", "search", "a@example.test"),
            join("annotations", "interest", "news", "a@example.test"),
        ]
        .into_iter()
        .enumerate()
        {
            assert_eq!(post(&s, body, &format!("192.0.2.{n}"), &[]).await.0, 202);
        }
        let list = |query: &str| {
            let s = s.clone();
            let path = format!("{ADMIN}{query}");
            async move { call(s, "GET", &path, json!({}), ADMIN_HEADERS).await }
        };
        let (status, all) = list("").await;
        assert_eq!(status, 200);
        assert_eq!(all["data"].as_array().unwrap().len(), 4);
        let free = list("?app_id=certifications&target_type=plan&target=free&status=pending")
            .await
            .1;
        assert_eq!(free["data"].as_array().unwrap().len(), 2);
        assert_eq!(free["data"][0]["plan_id"], PLAN);
        assert_eq!(free["data"][0]["target"], "free");
        assert_eq!(
            list("?target=news").await.1["data"][0]["app_id"],
            "annotations"
        );
        assert_eq!(
            list("?limit=1&offset=1").await.1["data"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        assert_eq!(list("?offset=4").await.1["data"], json!([]));
        for query in [
            "?limit=0",
            "?limit=101",
            "?offset=-1",
            "?offset=10001",
            "?status=open",
            "?target_type=billing",
            "?owner=x",
            "?limit=x",
        ] {
            let (status, error) = list(query).await;
            assert_eq!(status, 400, "{query}");
            assert_eq!(error["data"]["code"], "INVALID_WAITLIST_DATA");
        }
        let id = free["data"][0]["id"].as_str().unwrap().to_owned();
        let path = format!("{ADMIN}/{id}");
        let (status, updated) = call(
            s.clone(),
            "PATCH",
            &path,
            json!({"status":"contacted"}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(status, 200, "{updated}");
        assert_eq!(updated["data"]["status"], "contacted");
        assert_eq!(updated["data"]["email"], free["data"][0]["email"]);
        assert_eq!(
            list("?status=contacted").await.1["data"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        for body in [
            json!({"status":"deleted"}),
            json!({"status":"pending","email":"x@example.test"}),
            json!({}),
        ] {
            assert_eq!(
                call(s.clone(), "PATCH", &path, body, ADMIN_HEADERS).await.0,
                400
            );
        }
        let missing = call(
            s.clone(),
            "PATCH",
            &format!("{ADMIN}/{}", uuid::Uuid::new_v4()),
            json!({"status":"declined"}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(
            (missing.0.as_u16(), missing.1["data"]["code"].as_str()),
            (404, Some("WAITLIST_ENTRY_NOT_FOUND"))
        );
        assert_eq!(
            call(s.clone(), "DELETE", &path, json!({}), ADMIN_HEADERS)
                .await
                .0,
            405
        );
        let (status, conflict) = call(
            s.clone(),
            "DELETE",
            &format!("/apps/api/v1/admin/plans/{PLAN}"),
            json!({}),
            ADMIN_HEADERS,
        )
        .await;
        assert_eq!(
            (status.as_u16(), conflict["data"]["code"].as_str()),
            (409, Some("PLAN_RECORD_CONFLICT"))
        );
        assert_eq!(list("").await.1["data"].as_array().unwrap().len(), 4);
    }
    #[tokio::test]
    async fn admin_routes_use_the_central_administrator_guard_and_csrf() {
        let s = setup().await;
        for (sid, level) in [("user", 3), ("admin", 1)] {
            s.cache
                .set(
                    &format!("exchange_auth_app:{sid}"),
                    json!({"user_uuid_id":sid,"access_level":level,"csrf_token":"c"}),
                    60,
                    false,
                )
                .await
                .unwrap();
        }
        let path = format!("{ADMIN}/{}", uuid::Uuid::new_v4());
        let (status, error) = call(s.clone(), "GET", ADMIN, json!({}), &[]).await;
        assert_eq!(
            (status.as_u16(), error["data"]["code"].as_str()),
            (403, Some("AUTH_REQUIRED"))
        );
        let (status, error) = call(
            s.clone(),
            "GET",
            ADMIN,
            json!({}),
            &[("cookie", "sid=user")],
        )
        .await;
        assert_eq!(
            (status.as_u16(), error["data"]["code"].as_str()),
            (403, Some("ADMIN_REQUIRED"))
        );
        assert_eq!(
            call(
                s.clone(),
                "PATCH",
                &path,
                json!({"status":"declined"}),
                &[("cookie", "sid=user; csrf=c"), ("x-csrf-token", "c")]
            )
            .await
            .0,
            403
        );
        assert_eq!(
            call(
                s.clone(),
                "GET",
                ADMIN,
                json!({}),
                &[("cookie", "sid=admin")]
            )
            .await
            .0,
            200
        );
        let (status, error) = call(
            s.clone(),
            "PATCH",
            &path,
            json!({"status":"declined"}),
            &[("cookie", "sid=admin; csrf=c")],
        )
        .await;
        assert_eq!(
            (status.as_u16(), error["data"]["code"].as_str()),
            (403, Some("AUTH_REQUIRED"))
        );
        assert_eq!(
            call(
                s.clone(),
                "PATCH",
                &path,
                json!({"status":"declined"}),
                &[("cookie", "sid=admin; csrf=c"), ("x-csrf-token", "c")]
            )
            .await
            .0,
            404
        );
        assert_eq!(
            call(s.clone(), "PATCH", &path, json!("not an object"), &[])
                .await
                .0,
            403
        );
    }
    #[tokio::test]
    async fn schema_rejects_cross_app_mismatched_and_invalid_rows() {
        let s = setup().await;
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        let insert = "INSERT INTO app_waitlist_entries(id,app_id,target_type,plan_id,feature_id,interest,email,status) VALUES";
        sqlx::query(&format!(
            "{insert}('ok','certifications','plan','{PLAN}',NULL,NULL,'a@example.test','pending')"
        ))
        .execute(pool)
        .await
        .unwrap();
        for values in [
            "('x1','annotations','plan','{PLAN}',NULL,NULL,'b@example.test','pending')",
            "('x2','certifications','plan','other-plan',NULL,NULL,'b@example.test','pending')",
            "('x3','certifications','feature',NULL,NULL,'news','b@example.test','pending')",
            "('x4','certifications','plan','{PLAN}','feature',NULL,'b@example.test','pending')",
            "('x5','certifications','interest',NULL,NULL,'news','b@example.test','open')",
            "('x6','certifications','interest',NULL,NULL,'news','B@example.test','pending')",
            "('x7','missing','interest',NULL,NULL,'news','b@example.test','pending')",
            "('x8','certifications','plan','{PLAN}',NULL,NULL,'a@example.test','pending')",
            "('x9','certifications','billing',NULL,NULL,'news','b@example.test','pending')",
        ] {
            let sql = format!("{insert}{}", values.replace("{PLAN}", PLAN));
            assert!(sqlx::query(&sql).execute(pool).await.is_err(), "{sql}");
        }
        assert!(sqlx::query("INSERT INTO app_waitlist_entries(id,app_id,target_type,interest,email,user_id) VALUES('x10','certifications','interest','news','c@example.test','nobody')").execute(pool).await.is_err());
        for column in sqlx::query_as::<_, (i64, String, String)>(
            "SELECT cid,name,type FROM pragma_table_info('app_waitlist_entries')",
        )
        .fetch_all(pool)
        .await
        .unwrap()
        {
            assert!(
                !["JSON", "JSONB", "ARRAY"].contains(&column.2.to_uppercase().as_str()),
                "{}",
                column.1
            );
        }
    }
    #[tokio::test]
    async fn missing_schema_is_not_created_at_request_time() {
        let s = state().await;
        let (status, error) = post(
            &s,
            join("certifications", "plan", "free", "a@example.test"),
            "192.0.2.1",
            &[],
        )
        .await;
        assert_eq!(status, 503);
        assert_eq!(error["data"]["code"], "WAITLIST_SERVICE_UNAVAILABLE");
        assert!(!error.to_string().contains("SELECT"));
        let (status, _) = call(s.clone(), "GET", ADMIN, json!({}), ADMIN_HEADERS).await;
        assert_eq!(status, 503);
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        assert_eq!(
            sqlx::query_scalar::<_, i64>(
                "SELECT count(*) FROM sqlite_master WHERE name='app_waitlist_entries'"
            )
            .fetch_one(pool)
            .await
            .unwrap(),
            0
        );
    }
    #[tokio::test]
    async fn support_listing_is_filtered_paginated_and_owner_scoped_in_sql() {
        let s = state().await;
        let dal::database::Database::Sqlite(pool) = &s.db else {
            unreachable!()
        };
        sqlx::raw_sql(&include_str!("../migrations/001_app_catalog.sql").replace("public.", ""))
            .execute(pool)
            .await
            .unwrap();
        sqlx::raw_sql("INSERT INTO defaultdb_app(id,name) VALUES('reports','Reports'),('certifications','Certifications');
            INSERT INTO defaultdb_support_ticket VALUES('t1','a','reports','open','2026-01-01T00:00:00Z','2026-01-01T00:00:01Z'),('t2','a','certifications','closed','2026-01-01T00:00:00Z','2026-01-01T00:00:03Z'),('t3','b','reports','open','2026-01-01T00:00:00Z','2026-01-01T00:00:02Z')").execute(pool).await.unwrap();
        for (sid, user, level) in [("a", "a", 3), ("root", "root", 1)] {
            s.cache
                .set(
                    &format!("exchange_auth_app:{sid}"),
                    json!({"user_uuid_id":user,"access_level":level,"csrf_token":"c"}),
                    60,
                    false,
                )
                .await
                .unwrap();
        }
        let ids = |v: &Value| {
            v["data"]
                .as_array()
                .unwrap()
                .iter()
                .map(|t| t["id"].as_str().unwrap().to_owned())
                .collect::<Vec<_>>()
        };
        let get = |sid: &str, query: &str| {
            let cookie = format!("sid={sid}");
            let s = s.clone();
            let path = format!("/apps/support/v1/tickets{query}");
            async move { call(s, "GET", &path, json!({}), &[("cookie", cookie.as_str())]).await }
        };
        assert_eq!(ids(&get("a", "").await.1), ["t2", "t1"]);
        assert_eq!(ids(&get("root", "").await.1), ["t2", "t3", "t1"]);
        assert_eq!(
            ids(&get("root", "?source_app=%20Reports&status=open").await.1),
            ["t3", "t1"]
        );
        assert_eq!(ids(&get("root", "?limit=1&offset=1").await.1), ["t3"]);
        assert_eq!(ids(&get("a", "?status=closed").await.1), ["t2"]);
        assert_eq!(ids(&get("a", "?status=").await.1), ["t2", "t1"]);
        for query in ["?limit=0", "?limit=101", "?offset=10001", "?limit=x"] {
            assert_eq!(get("a", query).await.0, 422, "{query}");
        }
        assert_eq!(get("a", "?status=other").await.0, 400);
        s.cache
            .set(
                "exchange_auth_app:w",
                json!({"user_uuid_id":"a","access_level":3,"csrf_token":"c"}),
                60,
                false,
            )
            .await
            .unwrap();
        let (status, result) = call(
            s.clone(),
            "POST",
            "/apps/support/v1/tickets",
            json!({"source_app":"unknown","body":"Hello"}),
            &[
                ("content-type", "application/json"),
                ("cookie", "sid=w; csrf=c"),
                ("x-csrf-token", "c"),
            ],
        )
        .await;
        assert_eq!(status, 422, "{result}");
        assert_eq!(ids(&get("a", "").await.1).len(), 2);
    }
    #[tokio::test]
    async fn postgres_waitlist_and_support_constraints_on_disposable_test_database() {
        let Ok(connection) = std::env::var("TEST_WAITLIST_PG_URL") else {
            return;
        };
        let parsed = url::Url::parse(&connection).unwrap();
        assert_eq!(parsed.host_str(), Some("127.0.0.1"));
        assert!(
            parsed
                .port()
                .is_some_and(|port| port >= 1024 && port != 5432)
        );
        assert_eq!(
            parsed.path(),
            "/gateway57_test",
            "disposable named test database only"
        );
        let pool = sqlx::PgPool::connect(&connection).await.unwrap();
        sqlx::raw_sql("CREATE TABLE IF NOT EXISTS defaultdb_user(id SERIAL PRIMARY KEY,uuid_id VARCHAR(64) NOT NULL UNIQUE,email VARCHAR(320) NOT NULL UNIQUE,access_level INTEGER NOT NULL DEFAULT 3);
            CREATE TABLE IF NOT EXISTS defaultdb_support_ticket(id UUID PRIMARY KEY,user_id VARCHAR(64) NOT NULL,source_app VARCHAR(64) NOT NULL,status VARCHAR(32) NOT NULL DEFAULT 'open',created_at TIMESTAMPTZ NOT NULL DEFAULT now(),updated_at TIMESTAMPTZ NOT NULL DEFAULT now())").execute(&pool).await.unwrap();
        for _ in 0..2 {
            for schema in [
                include_str!("../migrations/001_app_catalog.sql"),
                include_str!("../migrations/004_app_plans.sql"),
                include_str!("../migrations/005_central_waitlist.sql"),
                include_str!("../migrations/006_support_ticket_constraints.sql"),
            ] {
                sqlx::raw_sql(schema).execute(&pool).await.unwrap();
            }
        }
        let app = format!("wl-{}", uuid::Uuid::new_v4().simple());
        let other = format!("wl-{}", uuid::Uuid::new_v4().simple());
        let user = uuid::Uuid::new_v4().simple().to_string();
        let email = format!("{user}@example.test");
        sqlx::query(
            "INSERT INTO defaultdb_app(id,name,is_active) VALUES($1,'Test',true),($2,'Other',true)",
        )
        .bind(&app)
        .bind(&other)
        .execute(&pool)
        .await
        .unwrap();
        sqlx::query("INSERT INTO defaultdb_user(uuid_id,email) VALUES($1,$2)")
            .bind(&user)
            .bind(&email)
            .execute(&pool)
            .await
            .unwrap();
        let plan = uuid::Uuid::new_v4().to_string();
        sqlx::query(
            "INSERT INTO app_plans(id,app_id,code,name,is_active) VALUES($1,$2,'free','Free',true)",
        )
        .bind(&plan)
        .bind(&app)
        .execute(&pool)
        .await
        .unwrap();
        let mut s = state().await;
        s.db = dal::database::Database::Pg(pool.clone());
        let request = |kind: &str, target: &str, mail: &str| Join {
            app_id: app.clone(),
            target_type: kind.into(),
            target: target.into(),
            email: mail.into(),
        };
        waitlist::join(
            &s,
            waitlist::validate(request("plan", "free", &email)).unwrap(),
            None,
        )
        .await
        .unwrap();
        waitlist::join(
            &s,
            waitlist::validate(request("plan", "free", &email.to_uppercase())).unwrap(),
            Some(user.clone()),
        )
        .await
        .unwrap();
        waitlist::join(
            &s,
            waitlist::validate(request("interest", "news", &email)).unwrap(),
            None,
        )
        .await
        .unwrap();
        let filter = |target: Option<&str>| Filter {
            app_id: Some(app.clone()),
            target: target.map(Into::into),
            ..Default::default()
        };
        let entries = waitlist::entries(&s, filter(None)).await.unwrap();
        assert_eq!(entries.len(), 2);
        let planned = waitlist::entries(&s, filter(Some("free"))).await.unwrap();
        assert_eq!(planned.len(), 1);
        assert_eq!(planned[0].user_id.as_deref(), Some(user.as_str()));
        assert_eq!(planned[0].plan_id.as_deref(), Some(plan.as_str()));
        let updated = waitlist::update(
            &s,
            &planned[0].id,
            StatusUpdate {
                status: "converted".into(),
            },
        )
        .await
        .unwrap();
        assert_eq!(updated.status, "converted");
        assert!(updated.updated_at >= updated.created_at);
        assert!(sqlx::query("INSERT INTO app_waitlist_entries(id,app_id,target_type,plan_id,email) VALUES('cross',$1,'plan',$2,'x@example.test')").bind(&other).bind(&plan).execute(&pool).await.is_err());
        assert!(
            sqlx::query("UPDATE app_waitlist_entries SET status='open' WHERE app_id=$1")
                .bind(&app)
                .execute(&pool)
                .await
                .is_err()
        );
        assert!(
            sqlx::query("DELETE FROM app_plans WHERE id=$1")
                .bind(&plan)
                .execute(&pool)
                .await
                .is_err()
        );
        let ticket = |source: &str, status: &str| {
            sqlx::query("INSERT INTO defaultdb_support_ticket(id,user_id,source_app,status) VALUES(CAST($1 AS UUID),$2,$3,$4)")
                .bind(uuid::Uuid::new_v4().to_string())
                .bind(user.clone())
                .bind(source.to_owned())
                .bind(status.to_owned())
        };
        ticket(&app, "open").execute(&pool).await.unwrap();
        ticket(&other, "closed").execute(&pool).await.unwrap();
        assert!(
            ticket("unregistered-app", "open")
                .execute(&pool)
                .await
                .is_err()
        );
        assert!(ticket(&app, "archived").execute(&pool).await.is_err());
        assert!(
            sqlx::query("INSERT INTO defaultdb_support_ticket(id,user_id,source_app,status) VALUES(CAST($1 AS UUID),'missing-user',$2,'open')")
                .bind(uuid::Uuid::new_v4().to_string())
                .bind(&app)
                .execute(&pool)
                .await
                .is_err()
        );
        let page =
            s.db.support_tickets(Some(&user), Some(&app), Some("open"), 50, 0)
                .await
                .unwrap();
        assert_eq!(page.len(), 1);
        assert_eq!(page[0]["source_app"], app.as_str());
        assert_eq!(
            s.db.support_tickets(Some(&user), None, None, 1, 1)
                .await
                .unwrap()
                .len(),
            1
        );
        assert!(
            s.db.support_tickets(Some("nobody"), None, None, 50, 0)
                .await
                .unwrap()
                .is_empty()
        );
        let forbidden: i64 = sqlx::query_scalar("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name IN ('app_waitlist_entries','defaultdb_support_ticket') AND data_type IN ('json','jsonb','ARRAY')").fetch_one(&pool).await.unwrap();
        assert_eq!(forbidden, 0);
        sqlx::query("DELETE FROM defaultdb_support_ticket WHERE user_id=$1")
            .bind(&user)
            .execute(&pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM app_waitlist_entries WHERE app_id=$1")
            .bind(&app)
            .execute(&pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM app_plans WHERE app_id=$1")
            .bind(&app)
            .execute(&pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM defaultdb_app WHERE id IN ($1,$2)")
            .bind(&app)
            .bind(&other)
            .execute(&pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM defaultdb_user WHERE uuid_id=$1")
            .bind(&user)
            .execute(&pool)
            .await
            .unwrap();
    }
}

#[tokio::test]
async fn proxy_display_name_uses_current_account_and_strips_spoofed_headers() {
    use axum::{Router, extract::Request as Incoming, routing::any};
    let upstream = Router::new().fallback(any(|request: Incoming| async move {
        axum::Json(
            json!({"name": request.headers().get("x-display-name").map(|v| v.to_str().unwrap())}),
        )
    }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, upstream).await.unwrap();
    });
    let mut s = state().await;
    for app in ["CORTEX_UPSTREAM", "ANNOTATIONS_UPSTREAM", "DOMAIN_UPSTREAM"] {
        Arc::make_mut(&mut s.settings.values).insert(app.into(), format!("http://{address}"));
    }
    s.db.insert("defaultdb_user", &json!({"id":1,"uuid_id":"account"}))
        .await
        .unwrap();
    s.cache
        .set(
            "exchange_auth_app:named",
            json!({"user_id":1,"user_uuid_id":"account","access_level":1}),
            60,
            false,
        )
        .await
        .unwrap();
    for (first, last, expected) in [
        (json!("สมชาย"), json!("ใจดี"), Some("สมชาย ใจดี")),
        (json!("José"), json!("Gonçalves"), Some("José Gonçalves")),
        (json!(" A+%\r\n"), Value::Null, Some(" A+%\r\n")),
        (Value::Null, json!("Silva"), Some("Silva")),
        (json!(" "), Value::Null, None),
    ] {
        s.db.update(
            "defaultdb_user",
            &json!(1),
            &json!({"first_name":first,"last_name":last}),
        )
        .await
        .unwrap();
        for path in [
            "/apps/cortex/v1/private",
            "/apps/annotations/v1/admin/posts",
        ] {
            let (status, value) = call(
                s.clone(),
                "GET",
                path,
                json!({}),
                &[
                    ("cookie", "sid=named"),
                    ("x-display-name", "spoofed"),
                    ("X-Display-Name", "another-spoof"),
                ],
            )
            .await;
            assert_eq!(status, 200, "{path}");
            let decoded = value["name"].as_str().map(|v| {
                percent_encoding::percent_decode_str(v)
                    .decode_utf8()
                    .unwrap()
                    .into_owned()
            });
            assert_eq!(decoded.as_deref(), expected, "{path}");
        }
    }
    for path in ["/apps/domain/v1/projects", "/apps/annotations/v1/catalog"] {
        let (status, value) = call(
            s.clone(),
            "GET",
            path,
            json!({}),
            &[("x-display-name", "spoofed")],
        )
        .await;
        assert_eq!(status, 200, "{path}");
        assert!(value["name"].is_null(), "{path}");
    }
    task.abort();
}

#[tokio::test]
async fn generic_proxy_permission_headers_are_gateway_owned() {
    use axum::{Router, extract::Request as Incoming, routing::any};
    let upstream = Router::new().fallback(any(|request: Incoming| async move {
        let h=request.headers();
        axum::Json(json!({"access":h.get("x-access-level").map(|v|v.to_str().unwrap()),"admin":h.get("x-project-admin").map(|v|v.to_str().unwrap())}))
    }));
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let task = tokio::spawn(async move {
        axum::serve(listener, upstream).await.unwrap();
    });
    let mut s = state().await;
    Arc::make_mut(&mut s.settings.values)
        .insert("DOMAIN_UPSTREAM".into(), format!("http://{address}"));
    let fake = [
        ("x-access-level", "1"),
        ("X-Access-Level", "2"),
        ("x-project-admin", "true"),
        ("X-Project-Admin", "true"),
    ];
    let (status, value) = call(
        s.clone(),
        "GET",
        "/apps/domain/v1/projects",
        json!({}),
        &fake,
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(value, json!({"access":null,"admin":null}));
    let mut api_key = fake.to_vec();
    api_key.push(("authorization", "test-admin"));
    let (status, value) = call(
        s.clone(),
        "POST",
        "/apps/domain/v1/projects",
        json!({}),
        &api_key,
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(value, json!({"access":null,"admin":null}));
    s.cache
        .set(
            "exchange_auth_app:permissions",
            json!({"user_uuid_id":"account","access_level":3,"is_project_admin":false}),
            60,
            false,
        )
        .await
        .unwrap();
    let mut session = fake.to_vec();
    session.push(("cookie", "sid=permissions"));
    let (status, value) = call(
        s,
        "GET",
        "/apps/domain/v1/legal/status",
        json!({}),
        &session,
    )
    .await;
    assert_eq!(status, 200);
    assert_eq!(value, json!({"access":"3","admin":"false"}));
    task.abort();
}
