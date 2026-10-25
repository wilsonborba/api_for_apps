use super::*;
pub fn page() -> Response {
    axum::response::Html(include_str!("assets/docs.html")).into_response()
}
pub fn favicon() -> Response {
    (
        [(axum::http::header::CONTENT_TYPE, "image/svg+xml")],
        include_str!("assets/favicon.svg"),
    )
        .into_response()
}
pub fn spec() -> Response {
    axum::Json(crate::domain::documentation::current()).into_response()
}

pub fn hello() -> Response {
    static VERSES: std::sync::LazyLock<Vec<Vec<Vec<Value>>>> = std::sync::LazyLock::new(|| {
        serde_json::from_str(include_str!("../dal/data/verses.json"))
            .expect("Embedded verse dataset")
    });
    let b = &*VERSES;
    if b.is_empty() {
        return response(500, "Verse data unavailable", Value::Null);
    }
    let book = &b[rand::random::<u64>() as usize % b.len()];
    let chapter = &book[rand::random::<u64>() as usize % book.len()];
    let verse = &chapter[rand::random::<u64>() as usize % chapter.len()];
    // Preserve the existing missing-KJV-data failure until owner resolves #48.
    if verse.is_null() {
        return (StatusCode::INTERNAL_SERVER_ERROR, "Internal Server Error").into_response();
    }
    response(
        200,
        "Hello, World, this is an opened test endpoint.",
        verse.clone(),
    )
}
