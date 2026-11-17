use super::*;
use crate::domain::{
    models::plans::{AppQuery, Create, Membership, Update},
    services::plans,
};

pub fn route(path: &str) -> bool {
    path == "/apps/api/v1/plans"
        || path == "/apps/api/v1/admin/plans"
        || path.starts_with("/apps/api/v1/admin/plans/")
        || path == "/apps/api/v1/admin/features"
        || path.starts_with("/apps/api/v1/admin/features/")
        || path == "/apps/api/v1/admin/plan-features"
        || path.starts_with("/apps/api/v1/admin/plan-features/")
}
fn input<T: serde::de::DeserializeOwned>(body: &Bytes) -> anyhow::Result<T> {
    serde_json::from_slice(body).map_err(|_| plans::Failure::Invalid.into())
}
fn query(value: Option<&str>) -> anyhow::Result<AppQuery> {
    serde_urlencoded::from_str(value.unwrap_or("")).map_err(|_| plans::Failure::Invalid.into())
}
pub async fn handle(
    s: &State,
    m: &Method,
    path: &str,
    q: Option<&str>,
    h: &HeaderMap,
    b: Bytes,
) -> Response {
    if path != "/apps/api/v1/plans"
        && let Err(error) = auth::verify(s, h, m.as_str(), true).await
    {
        return response(
            403,
            "Administrator access is required.",
            json!({"code":if error.to_string().starts_with("Forbidden") {"ADMIN_REQUIRED"} else {"AUTH_REQUIRED"}}),
        );
    }
    let result: anyhow::Result<(u16, Value)> = async {
        match (m.as_str(), path) {
            ("GET", "/apps/api/v1/plans") => {
                let app = query(q)?;
                Ok((
                    200,
                    serde_json::to_value(plans::plans(s, &app.app_id, true).await?)?,
                ))
            }
            ("GET", "/apps/api/v1/admin/plans") => {
                let app = query(q)?;
                Ok((
                    200,
                    serde_json::to_value(plans::plans(s, &app.app_id, false).await?)?,
                ))
            }
            ("GET", "/apps/api/v1/admin/features") => {
                let app = query(q)?;
                Ok((
                    200,
                    serde_json::to_value(plans::features(s, &app.app_id).await?)?,
                ))
            }
            ("POST", "/apps/api/v1/admin/plans") => Ok((
                201,
                serde_json::to_value(plans::create_plan(s, input::<Create>(&b)?).await?)?,
            )),
            ("POST", "/apps/api/v1/admin/features") => Ok((
                201,
                serde_json::to_value(plans::create_feature(s, input::<Create>(&b)?).await?)?,
            )),
            ("POST", "/apps/api/v1/admin/plan-features") => {
                let v = input::<Membership>(&b)?;
                plans::attach(s, &v).await?;
                Ok((201, json!({"plan_id":v.plan_id,"feature_id":v.feature_id})))
            }
            _ => {
                if let Some(id) = path.strip_prefix("/apps/api/v1/admin/plans/") {
                    match m.as_str() {
                        "PATCH" => Ok((
                            200,
                            serde_json::to_value(
                                plans::update_plan(s, id, input::<Update>(&b)?).await?,
                            )?,
                        )),
                        "DELETE" => {
                            plans::delete_plan(s, id).await?;
                            Ok((200, Value::Null))
                        }
                        _ => Ok((405, json!({"code":"METHOD_NOT_ALLOWED"}))),
                    }
                } else if let Some(id) = path.strip_prefix("/apps/api/v1/admin/features/") {
                    match m.as_str() {
                        "PATCH" => Ok((
                            200,
                            serde_json::to_value(
                                plans::update_feature(s, id, input::<Update>(&b)?).await?,
                            )?,
                        )),
                        "DELETE" => {
                            plans::delete_feature(s, id).await?;
                            Ok((200, Value::Null))
                        }
                        _ => Ok((405, json!({"code":"METHOD_NOT_ALLOWED"}))),
                    }
                } else if let Some(ids) = path.strip_prefix("/apps/api/v1/admin/plan-features/") {
                    let mut ids = ids.split('/');
                    match (m.as_str(), ids.next(), ids.next(), ids.next()) {
                        ("DELETE", Some(plan), Some(feature), None) => {
                            plans::detach(s, plan, feature).await?;
                            Ok((200, Value::Null))
                        }
                        _ => Ok((405, json!({"code":"METHOD_NOT_ALLOWED"}))),
                    }
                } else {
                    Ok((405, json!({"code":"METHOD_NOT_ALLOWED"})))
                }
            }
        }
    }
    .await;
    let mut r = match result {
        Ok((status, data)) => response(
            status,
            if status < 400 {
                "Success"
            } else {
                "Method Not Allowed"
            },
            data,
        ),
        Err(error) => match error.downcast_ref::<plans::Failure>() {
            Some(error) => response(
                error.status(),
                error.message(),
                json!({"code":error.code()}),
            ),
            None => response(
                503,
                "Plan service is unavailable.",
                json!({"code":"PLAN_SERVICE_UNAVAILABLE"}),
            ),
        },
    };
    r.headers_mut()
        .insert("cache-control", "no-store".parse().unwrap());
    r
}
