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

pub fn asset(path: &str, headers: &HeaderMap) -> Response {
    const SCALAR: &[u8] = include_bytes!("assets/vendor/scalar-1.76.0.js.gz");
    static SCALAR_RAW: std::sync::LazyLock<Vec<u8>> = std::sync::LazyLock::new(|| {
        use std::io::Read;
        let mut raw = Vec::new();
        flate2::read::GzDecoder::new(SCALAR)
            .read_to_end(&mut raw)
            .expect("Embedded Scalar gzip");
        raw
    });
    let (mime, data, compressed): (&str, &[u8], bool) = match path {
        "/docs/assets/initialize.js" => (
            "text/javascript; charset=utf-8",
            include_bytes!("assets/initialize.js"),
            false,
        ),
        "/docs/assets/scalar-1.76.0.js" => {
            let gzip = headers
                .get("accept-encoding")
                .and_then(|h| h.to_str().ok())
                .is_some_and(|h| {
                    h.split(',').any(|v| {
                        let mut parts = v.trim().split(';');
                        parts.next() == Some("gzip")
                            && !parts.any(|p| {
                                p.trim()
                                    .strip_prefix("q=")
                                    .is_some_and(|q| q.parse::<f32>().unwrap_or(0.0) == 0.0)
                            })
                    })
                });
            (
                "text/javascript; charset=utf-8",
                if gzip { SCALAR } else { &SCALAR_RAW },
                gzip,
            )
        }
        "/docs/assets/ubuntu-sans-latin.woff2" => (
            "font/woff2",
            include_bytes!("assets/vendor/ubuntu-sans-latin.woff2"),
            false,
        ),
        "/docs/assets/ubuntu-sans-mono-latin.woff2" => (
            "font/woff2",
            include_bytes!("assets/vendor/ubuntu-sans-mono-latin.woff2"),
            false,
        ),
        _ => return StatusCode::NOT_FOUND.into_response(),
    };
    let mut out = (
        [
            ("content-type", mime),
            ("cache-control", "public, max-age=86400"),
            ("vary", "Accept-Encoding"),
        ],
        data,
    )
        .into_response();
    if compressed {
        out.headers_mut()
            .insert("content-encoding", "gzip".parse().unwrap());
    }
    out
}

pub fn hello() -> Response {
    static VERSES: std::sync::LazyLock<Vec<Vec<Vec<Value>>>> = std::sync::LazyLock::new(|| {
        let books: Vec<Vec<Vec<Value>>> =
            serde_json::from_str(include_str!("../dal/data/verses.json"))
                .expect("Embedded verse dataset");
        books
            .into_iter()
            .map(|book| {
                book.into_iter()
                    .map(|chapter| {
                        chapter
                            .into_iter()
                            .filter(|verse| !verse.is_null())
                            .collect::<Vec<_>>()
                    })
                    .filter(|chapter| !chapter.is_empty())
                    .collect::<Vec<_>>()
            })
            .filter(|book| !book.is_empty())
            .collect()
    });
    let b = &*VERSES;
    if b.is_empty() {
        return response(500, "Verse data unavailable", Value::Null);
    }
    let book = &b[rand::random::<u64>() as usize % b.len()];
    let chapter = &book[rand::random::<u64>() as usize % book.len()];
    let verse = &chapter[rand::random::<u64>() as usize % chapter.len()];
    response(
        200,
        "Hello, World, this is an opened test endpoint.",
        verse.clone(),
    )
}
