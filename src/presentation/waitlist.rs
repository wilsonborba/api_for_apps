use super::*;
use crate::domain::{
    models::waitlist::{Filter, Join, StatusUpdate},
    services::waitlist,
};

const PUBLIC: &str = "/apps/api/v1/waitlist";
const ADMIN: &str = "/apps/api/v1/admin/waitlist";
pub fn route(path: &str) -> bool {
    path == PUBLIC || path == ADMIN || path.starts_with("/apps/api/v1/admin/waitlist/")
}
fn input<T: serde::de::DeserializeOwned>(body: &Bytes) -> anyhow::Result<T> {
    serde_json::from_slice(body).map_err(|_| waitlist::Failure::Invalid.into())
}
/// Public sign-up. The same answer is returned for new and repeated emails.
async fn join(s: &State, h: &HeaderMap, b: &Bytes, ip: &str) -> anyhow::Result<(u16, Value)> {
    let request = waitlist::validate(input::<Join>(b)?)?;
    if let Err(error) = auth::rate(s, h, ip, "waitlist", Some(&request.email), false).await {
        if error.to_string().starts_with("Too many") {
            anyhow::bail!(waitlist::Failure::RateLimited)
        }
        return Err(error);
    }
    let user = auth::session(s, h).await.ok().flatten().and_then(|u| {
        let own = waitlist::email(text(&u, "email")).as_deref() == Some(request.email.as_str());
        own.then(|| text(&u, "user_uuid_id").to_owned())
            .filter(|id| !id.is_empty())
    });
    waitlist::join(s, request, user).await?;
    Ok((202, Value::Null))
}
pub async fn handle(
    s: &State,
    m: &Method,
    path: &str,
    q: Option<&str>,
    h: &HeaderMap,
    b: Bytes,
    ip: &str,
) -> Response {
    if path != PUBLIC
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
            ("POST", PUBLIC) => join(s, h, &b, ip).await,
            ("GET", ADMIN) => {
                let filter: Filter = serde_urlencoded::from_str(q.unwrap_or(""))
                    .map_err(|_| waitlist::Failure::Invalid)?;
                Ok((
                    200,
                    serde_json::to_value(waitlist::entries(s, filter).await?)?,
                ))
            }
            ("PATCH", _) if path.starts_with("/apps/api/v1/admin/waitlist/") => {
                let id = &path["/apps/api/v1/admin/waitlist/".len()..];
                Ok((
                    200,
                    serde_json::to_value(
                        waitlist::update(s, id, input::<StatusUpdate>(&b)?).await?,
                    )?,
                ))
            }
            _ => Ok((405, json!({"code":"METHOD_NOT_ALLOWED"}))),
        }
    }
    .await;
    let mut r = match result {
        Ok((202, data)) => response(202, "Waitlist request received.", data),
        Ok((status, data)) => response(
            status,
            if status < 400 {
                "Success"
            } else {
                "Method Not Allowed"
            },
            data,
        ),
        Err(error) => match error.downcast_ref::<waitlist::Failure>() {
            Some(error) => response(
                error.status(),
                error.message(),
                json!({"code":error.code()}),
            ),
            None => response(
                503,
                "Waitlist service is unavailable.",
                json!({"code":"WAITLIST_SERVICE_UNAVAILABLE"}),
            ),
        },
    };
    r.headers_mut()
        .insert("cache-control", "no-store".parse().unwrap());
    r
}
