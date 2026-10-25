use super::*;
use crate::domain::support;
pub async fn handle(
    s: &State,
    m: &Method,
    path: &str,
    q: Option<&str>,
    h: &HeaderMap,
    b: Bytes,
) -> Response {
    if let Err(e) = auth::verify(s, h, m.as_str(), false).await {
        return detail(403, &e.to_string());
    }
    let u = match auth::session(s, h).await {
        Ok(Some(u)) if u["user_uuid_id"].is_string() => u,
        _ => return detail(403, "Support tickets require an authenticated user session"),
    };
    let admin = u["access_level"] == 1;
    if path == "attachments" && m == Method::POST {
        return attachment(s, &u, h, b).await;
    }
    let parts: Vec<_> = path.split('/').collect();
    if parts.first() != Some(&"tickets") {
        return detail(404, "Not Found");
    }
    if path == "tickets" && m == Method::GET {
        let params: std::collections::HashMap<_, _> =
            url::form_urlencoded::parse(q.unwrap_or("").as_bytes())
                .into_owned()
                .collect();
        if params
            .get("source_app")
            .is_some_and(|v| v.chars().count() > 64)
            || params.get("status").is_some_and(|v| v.chars().count() > 32)
        {
            return detail(422, "Support filter exceeds maximum length");
        }
        if let Some(status) = params.get("status")
            && !status.is_empty()
            && !["open", "pending", "resolved", "closed"].contains(&status.as_str())
        {
            return response(
                400,
                "Invalid status filter. Expected one of ('open', 'pending', 'resolved', 'closed').",
                Value::Null,
            );
        }
        return match s.db.all("defaultdb_support_ticket").await {
            Ok(mut ts) => {
                ts.retain(|t| {
                    (admin || t["user_id"] == u["user_uuid_id"])
                        && params.get("source_app").is_none_or(|a| {
                            a.trim().is_empty() || t["source_app"] == a.trim().to_lowercase()
                        })
                        && params
                            .get("status")
                            .is_none_or(|a| a.is_empty() || t["status"] == *a)
                });
                ts.sort_by(|a, b| text(b, "updated_at").cmp(text(a, "updated_at")));
                response(200, "Support tickets retrieved successfully.", json!(ts))
            }
            Err(_) => response(400, "Failed to retrieve support tickets.", Value::Null),
        };
    }
    let body = if m == Method::POST {
        match parse(&b) {
            Ok(v) => v,
            Err(r) => return *r,
        }
    } else {
        Value::Null
    };
    if m == Method::POST
        && (!valid_string(&body, "body", 1, 8000, false)
            || !valid_string(&body, "attachment_reference", 0, 2000, true))
    {
        return detail(422, "Invalid support message");
    }
    let result: anyhow::Result<(u16, &str, Value)> = async {
        if path == "tickets" && m == Method::POST {
            if !valid_string(&body, "source_app", 2, 64, false)
                || !valid_string(&body, "subject", 0, 200, true)
            {
                return Ok((422, "Invalid support ticket", Value::Null));
            }
            return Ok((
                201,
                "Support ticket created successfully.",
                support::create(s, &u, &body).await?,
            ));
        }
        let id = *parts
            .get(1)
            .ok_or_else(|| anyhow::anyhow!("Support ticket not found."))?;
        if parts.len() == 2 && m == Method::GET {
            return Ok((
                200,
                "Support ticket retrieved successfully.",
                support::get(s, id, &u).await?,
            ));
        }
        if parts.len() == 3 && parts[2] == "messages" && m == Method::POST {
            return Ok((
                201,
                "Message posted successfully.",
                support::reply(s, id, &u, &body).await?,
            ));
        }
        if parts.len() == 3 && parts[2] == "read" && m == Method::PATCH {
            let out = support::mark(s, id, None, &u).await?;
            return Ok((
                200,
                "Support ticket marked as read.",
                json!({"messages_marked_read":out["count"]}),
            ));
        }
        if parts.len() == 5 && parts[2] == "messages" && parts[4] == "read" && m == Method::PATCH {
            let out = support::mark(s, id, Some(parts[3]), &u).await?;
            return Ok(if out["found"] == true {
                (200, "Message marked as read.", Value::Null)
            } else {
                (
                    404,
                    "Message not found on this support ticket.",
                    Value::Null,
                )
            });
        }
        Ok((405, "Method Not Allowed", Value::Null))
    }
    .await;
    match result {
        Ok((status, msg, v)) => response(status, msg, v),
        Err(e) if e.to_string() == "Support ticket not found." => {
            response(404, "Support ticket not found.", Value::Null)
        }
        Err(_) => response(
            400,
            if path == "tickets" {
                "Failed to create the support ticket."
            } else if parts.get(2) == Some(&"messages") {
                "Failed to post the message."
            } else {
                "Failed to retrieve the support ticket."
            },
            Value::Null,
        ),
    }
}
async fn attachment(s: &State, u: &Value, h: &HeaderMap, b: Bytes) -> Response {
    let boundary = match multer::parse_boundary(auth::header(h, "content-type")) {
        Ok(v) => v,
        Err(_) => return detail(422, "Invalid multipart attachment"),
    };
    let input = futures_util::stream::once(async move { Ok::<_, std::convert::Infallible>(b) });
    let mut multipart = multer::Multipart::new(input, boundary);
    let mut file = None;
    while let Ok(Some(field)) = multipart.next_field().await {
        if field.name() != Some("file") {
            continue;
        }
        let name = field.file_name().unwrap_or("attachment").to_owned();
        let mime = field
            .content_type()
            .map(ToString::to_string)
            .unwrap_or_else(|| "application/octet-stream".to_owned());
        if let Ok(data) = field.bytes().await {
            file = Some((name, mime, data));
        }
        break;
    }
    let Some((name, mime, data)) = file else {
        return detail(422, "File is required");
    };
    if data.len() > 15 * 1024 * 1024 {
        return response(
            400,
            "Attachment exceeds the maximum allowed size.",
            Value::Null,
        );
    }
    let key = s.settings.get("FSM_APP_KEY");
    if key.is_empty() {
        return response(503, "Attachment storage is not configured.", Value::Null);
    }
    let result = crate::dal::remote::fsm::upload(
        &s.client,
        &s.settings,
        &format!("support-{}", text(u, "user_uuid_id")),
        name,
        &mime,
        data.to_vec(),
    )
    .await;
    match result {
        Ok(key) => response(
            201,
            "Attachment uploaded successfully.",
            json!({"attachment_reference":key}),
        ),
        Err(_) => response(502, "Failed to upload the attachment.", Value::Null),
    }
}
