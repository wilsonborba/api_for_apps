//! Validate gateway-owned typed JSON using the same central contract used by Docs.
use super::*;
static CONTRACT: std::sync::LazyLock<Value> = std::sync::LazyLock::new(|| {
    serde_json::from_str(include_str!("assets/gateway_contracts.json")).unwrap()
});
pub fn method_allowed(method: &str, path: &str) -> Option<bool> {
    CONTRACT["paths"]
        .get(path)
        .and_then(Value::as_object)
        .map(|m| m.contains_key(&method.to_lowercase()))
}
pub fn request(method: &str, path: &str, body: &Bytes) -> Option<Response> {
    let op = &CONTRACT["paths"][path][method.to_lowercase()];
    let sc = op.pointer("/requestBody/content/application~1json/schema")?;
    // Exchange and profile have dynamic Python contracts. Their handlers preserve those rules.
    if matches!(path, "/apps/api/v1/exchange" | "/user/info/v1/") {
        return None;
    }
    let value=match serde_json::from_slice::<Value>(body){Ok(v)=>v,Err(_)=>return Some((StatusCode::UNPROCESSABLE_ENTITY,axum::Json(json!({"detail":[{"type":"json_invalid","loc":["body",0],"msg":"JSON decode error","input":{},"ctx":{"error":"Invalid JSON"}}]}))).into_response())};
    let mut errors = vec![];
    check(sc, &value, vec![json!("body")], &mut errors);
    if errors.is_empty() {
        None
    } else {
        Some(
            (
                StatusCode::UNPROCESSABLE_ENTITY,
                axum::Json(json!({"detail":errors})),
            )
                .into_response(),
        )
    }
}
fn resolved(s: &Value) -> &Value {
    if let Some(r) = s["$ref"].as_str() {
        &CONTRACT["schemas"][r.rsplit('/').next().unwrap_or("")]
    } else {
        s
    }
}
fn check(schema: &Value, value: &Value, loc: Vec<Value>, errors: &mut Vec<Value>) {
    let s = resolved(schema);
    if let Some(types) = s["anyOf"].as_array() {
        if value.is_null() && types.iter().any(|t| t["type"] == "null") {
            return;
        }
        if let Some(t) = types.iter().find(|t| t["type"] != "null") {
            check(t, value, loc, errors)
        }
        return;
    }
    let kind = s["type"].as_str().unwrap_or("");
    let mut err = |typ: &str, msg: &str, ctx: Option<Value>| {
        let mut e = json!({"type":typ,"loc":loc,"msg":msg,"input":value});
        if let Some(ctx) = ctx {
            e["ctx"] = ctx
        }
        errors.push(e);
    };
    match kind {
        "object" => {
            let Some(obj) = value.as_object() else {
                err(
                    "model_attributes_type",
                    "Input should be a valid dictionary or object to extract fields from",
                    None,
                );
                return;
            };
            if let Some(required) = s["required"].as_array() {
                for key in required.iter().filter_map(Value::as_str) {
                    if !obj.contains_key(key) {
                        let mut l = loc.clone();
                        l.push(json!(key));
                        errors.push(
                            json!({"type":"missing","loc":l,"msg":"Field required","input":value}),
                        );
                    }
                }
            }
            if let Some(props) = s["properties"].as_object() {
                for (key, sc) in props {
                    if let Some(v) = obj.get(key) {
                        let mut l = loc.clone();
                        l.push(json!(key));
                        check(sc, v, l, errors)
                    }
                }
            }
        }
        "string" => {
            let Some(v) = value.as_str() else {
                err("string_type", "Input should be a valid string", None);
                return;
            };
            let n = v.chars().count();
            if let Some(min) = s["minLength"].as_u64()
                && n < (min as usize)
            {
                err(
                    "string_too_short",
                    &format!(
                        "String should have at least {min} character{}",
                        if min == 1 { "" } else { "s" }
                    ),
                    Some(json!({"min_length":min})),
                )
            }
            if let Some(max) = s["maxLength"].as_u64()
                && n > (max as usize)
            {
                err(
                    "string_too_long",
                    &format!("String should have at most {max} characters"),
                    Some(json!({"max_length":max})),
                )
            }
            if let Some(pattern) = s["pattern"].as_str()
                && !regex::Regex::new(pattern).unwrap().is_match(v)
            {
                err(
                    "string_pattern_mismatch",
                    &format!("String should match pattern '{pattern}'"),
                    Some(json!({"pattern":pattern})),
                )
            }
        }
        "integer" => {
            if !value.is_i64() && !value.is_u64() {
                err("int_type", "Input should be a valid integer", None)
            }
        }
        "boolean" => {
            if !value.is_boolean() {
                err("bool_type", "Input should be a valid boolean", None)
            }
        }
        "array" => {
            if !value.is_array() {
                err("list_type", "Input should be a valid list", None)
            }
        }
        _ => {}
    }
}
