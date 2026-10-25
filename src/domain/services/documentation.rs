//! Central source-only discovery at runtime. No downstream OpenAPI requests.
//! The build inventory supplies detailed contracts. This scanner detects source edits
//! between gateway releases and refreshes route membership without requiring Python.
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    path::Path,
    sync::{LazyLock, Mutex},
    time::{Duration, Instant},
};
fn rx(pattern: &'static str) -> regex::Regex {
    static REGEXES: LazyLock<Mutex<HashMap<&'static str, regex::Regex>>> =
        LazyLock::new(|| Mutex::new(HashMap::new()));
    REGEXES
        .lock()
        .unwrap()
        .entry(pattern)
        .or_insert_with(|| regex::Regex::new(pattern).unwrap())
        .clone()
}
static CACHE: LazyLock<Mutex<Option<(Instant, Value)>>> = LazyLock::new(|| Mutex::new(None));
pub fn current() -> Value {
    let mut cache = CACHE.lock().unwrap_or_else(|e| e.into_inner());
    if let Some((when, value)) = &*cache
        && when.elapsed() < Duration::from_secs(10)
    {
        return value.clone();
    }
    let mut base: Value =
        serde_json::from_str(include_str!("../../presentation/assets/openapi.json"))
            .expect("Embedded central contract");
    if let Ok(text) = std::fs::read_to_string("src/presentation/assets/openapi.json")
        && let Ok(value) = serde_json::from_str::<Value>(&text)
        && value["paths"].is_object()
    {
        base = value;
    }
    let workspace = std::env::current_dir()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf));
    let result = workspace.map(|p| refresh(base.clone(), &p)).unwrap_or(base);
    *cache = Some((Instant::now(), result.clone()));
    result
}
fn methods(body: &str) -> Vec<String> {
    let r = rx(r"\b(get|post|put|patch|delete|head|options)\(");
    r.captures_iter(body).map(|m| m[1].to_owned()).collect()
}
fn python_routes(text: &str) -> Vec<(String, String, String)> {
    let mut prefixes = HashMap::new();
    let re = rx(r#"(?s)(\w+)\s*=\s*APIRouter\((.*?)\)"#);
    let pref = rx(r#"prefix\s*=\s*[\"']([^\"']*)[\"']"#);
    for c in re.captures_iter(text) {
        prefixes.insert(
            c[1].to_owned(),
            pref.captures(&c[2])
                .map(|x| x[1].to_owned())
                .unwrap_or_default(),
        );
    }
    let route = rx(
        r#"(?s)@(\w+)\.(get|post|put|patch|delete|head|options|websocket|api_route)\(\s*(?:f)?[\"']([^\"']*)[\"'](.*?)\)"#,
    );
    let summary = rx(r#"summary\s*=\s*[\"']([^\"']+)[\"']"#);
    let mut out = vec![];
    for c in route.captures_iter(text) {
        let path = format!(
            "{}{}",
            prefixes.get(&c[1]).map(String::as_str).unwrap_or(""),
            &c[3]
        );
        let title = summary
            .captures(&c[4])
            .map(|m| m[1].to_owned())
            .unwrap_or_else(|| format!("{} {}", &c[2].to_uppercase(), &path));
        if &c[2] == "api_route" {
            let ms = rx(r#"[\"'](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)[\"']"#);
            for m in ms.captures_iter(&c[4]) {
                out.push((path.clone(), m[1].to_lowercase(), title.clone()))
            }
        } else {
            out.push((
                path,
                if &c[2] == "websocket" {
                    "get".into()
                } else {
                    c[2].to_owned()
                },
                title,
            ))
        }
    }
    out
}
fn rust_routes(text: &str) -> Vec<(String, String, String)> {
    let route = rx(r#"\.route\(\s*\"([^\"]+)\"\s*,"#);
    let mut out = vec![];
    let boundary = text.find("pub fn router(").unwrap_or(0);
    for c in route.captures_iter(text) {
        let start = c.get(0).unwrap().end();
        let mut depth = 1;
        let mut end = start;
        for (i, ch) in text[start..].char_indices() {
            if ch == '(' {
                depth += 1
            }
            if ch == ')' {
                depth -= 1
            }
            if depth == 0 {
                end = start + i;
                break;
            }
        }
        let mut expr = text[start..end].trim().to_owned();
        if !expr.contains('(') {
            let binding =
                regex::Regex::new(&format!(r"(?s)let\s+{}\s*=\s*(.*?);", regex::escape(&expr)))
                    .unwrap();
            if let Some(b) = binding.captures(text) {
                expr = b[1].to_owned()
            }
        }
        let raw = rx(r":([A-Za-z_]\w*)")
            .replace_all(&c[1], "{$1}")
            .to_string();
        for m in methods(&expr) {
            if c.get(0).unwrap().start() < boundary {
                for prefix in ["/projects/{project}/admin", "/admin/projects/{project}"] {
                    if m == "get"
                        && prefix.starts_with("/projects/")
                        && [
                            "/schemas",
                            "/grants",
                            "/calculations",
                            "/reports/{report}/datasets/{dataset}/snapshots",
                        ]
                        .contains(&raw.as_str())
                    {
                        continue;
                    }
                    out.push((
                        format!("{prefix}{raw}"),
                        m.clone(),
                        format!("{} {raw}", m.to_uppercase()),
                    ))
                }
            } else {
                out.push((
                    raw.clone(),
                    m.clone(),
                    format!("{} {raw}", m.to_uppercase()),
                ))
            }
        }
    }
    out
}
pub fn refresh(mut spec: Value, workspace: &Path) -> Value {
    let registry: Value = serde_json::from_str(include_str!("../../core/apps.json")).unwrap();
    let defaults: Value = serde_json::from_str(include_str!("../../core/defaults.json")).unwrap();
    let mut unresolved = vec![];
    for (app, entry) in registry.as_object().unwrap() {
        let repo = workspace.join(entry["source"].as_str().unwrap());
        if !repo.exists() {
            unresolved.push(json!({"app":app,"reason":"Source repository unavailable; retaining last verified contract"}));
            continue;
        }
        let snapshot = match crate::dal::local::source_inventory::read(
            &repo,
            if entry["language"] == "rust" {
                "rs"
            } else {
                "py"
            },
        ) {
            Ok(v) => v,
            Err(_) => {
                unresolved.push(json!({"app":app,"reason":"Source snapshot unavailable; retaining last verified contract"}));
                continue;
            }
        };
        let mut found: HashSet<(String, String)> = HashSet::new();
        let mut scanned = HashSet::new();
        for source in snapshot.files {
            let file = source.path;
            let text = source.text;
            if entry["language"] == "rust" && !text.contains(".route(") {
                continue;
            }
            let relative = file
                .strip_prefix(workspace)
                .unwrap_or(&file)
                .to_string_lossy()
                .to_string();
            scanned.insert(relative.clone());
            let routes = if entry["language"] == "rust" {
                rust_routes(&text)
            } else {
                python_routes(&text)
            };
            for (path, method, title) in routes {
                if matches!(path.as_str(), "/docs" | "/scalar" | "/openapi.json") {
                    continue;
                }
                let path = rx(r"\{(\w+):path\}").replace_all(&path, "{$1}").to_string();
                let full = format!("/apps/{app}/v1{path}");
                found.insert((full.clone(), method.clone()));
                let previous_hash = spec["paths"][&full][&method]["x-source-tree-sha256"]
                    .as_str()
                    .map(str::to_owned);
                let old = &spec["paths"][&full][&method];
                if old.is_null() {
                    let mut parameters = vec![];
                    for c in rx(r"\{(\w+)\}").captures_iter(&full) {
                        parameters.push(json!({"name":&c[1],"in":"path","required":true,"schema":{"type":"string"}}))
                    }
                    let matches = |table: &str| {
                        defaults[table][app][method.to_uppercase()]
                            .as_array()
                            .is_some_and(|ps| {
                                ps.iter()
                                    .filter_map(Value::as_str)
                                    .any(|p| crate::core::settings::glob(p, &path))
                            })
                    };
                    let admin =
                        path.starts_with("/logs") || matches("ADMIN_PROTECTED_PROXY_ROUTES");
                    let public = !admin
                        && !matches("FORCE_AUTH_PROXY_ROUTES")
                        && matches("PUBLIC_PROXY_ROUTES");
                    spec["paths"][&full][&method] = json!({"operationId":format!("{}_{}_{}",app,method,rx(r"\W").replace_all(&path,"_")),"tags":[app],"summary":title,"description":format!("Discovered from the registered {app} service source after the gateway build. {} The source does not provide a centrally verified full contract for this new operation yet; refresh the central build inventory to infer typed fields and review examples.",if public{"Anonymous gateway access is allowed."}else if admin{"Administrator authorization is required."}else{"Session authorization is required. Mutable session requests require CSRF."}),"parameters":parameters,"responses":{"default":{"description":"Response contract requires central review; no schema is fabricated."}},"security":if public{json!([])}else{json!([{"SessionCookie":[]},{"AdminKey":[]}])},"x-source":relative,"x-discovery-gaps":["New source route: typed contract and examples require build-time inference or central override."]});
                }
                let op = &mut spec["paths"][&full][&method];
                op["x-source-current-sha256"] = json!(snapshot.sha256);
                if let Some(old_hash) = previous_hash {
                    if old_hash != snapshot.sha256 {
                        op["x-source-outdated"] = json!(true);
                        let mut gaps = op["x-discovery-gaps"]
                            .as_array()
                            .cloned()
                            .unwrap_or_default();
                        gaps.push(json!("Service source changed after contract generation. Regenerate central typed contracts; current route membership was checked."));
                        op["x-discovery-gaps"] = json!(gaps);
                    }
                } else {
                    op["x-source-tree-sha256"] = json!(snapshot.sha256);
                }
            }
        }
        // Only remove registrations from files this scanner could actually inspect.
        let paths = spec["paths"].as_object_mut().unwrap();
        let mut empty = vec![];
        for (path, methods) in paths.iter_mut() {
            if !path.starts_with(&format!("/apps/{app}/v1")) {
                continue;
            }
            if let Some(methods) = methods.as_object_mut() {
                methods.retain(|method, op| {
                    let source = op["x-source"]
                        .as_str()
                        .unwrap_or("")
                        .split(':')
                        .next()
                        .unwrap_or("");
                    !scanned.contains(source) || found.contains(&(path.clone(), method.clone()))
                });
                if methods.is_empty() {
                    empty.push(path.clone())
                }
            }
        }
        for path in empty {
            paths.remove(&path);
        }
    }
    let override_path = workspace.join("api_for_apps/src/presentation/assets/descriptions.json");
    if let Ok(text) = std::fs::read_to_string(override_path)
        && let Ok(Value::Object(overrides)) = serde_json::from_str::<Value>(&text)
    {
        for (key, over) in overrides {
            if let Some((method, path)) = key.split_once(' ')
                && let Some(op) = spec["paths"][path][method.to_lowercase()].as_object_mut()
                && let Some(over) = over.as_object()
            {
                op.extend(over.clone());
            }
        }
    }
    spec["x-source-discovery"] = json!({"mode":"central Rust source scan","refresh_seconds":10,"downstream_openapi_dependency":false,"unavailable_sources":unresolved});
    spec
}
