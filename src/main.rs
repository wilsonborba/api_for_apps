mod core;
mod dal;
mod domain;
mod presentation;
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let settings = core::settings::Settings::load();
    let (logs, _) = tokio::sync::broadcast::channel(256);
    tracing_subscriber::fmt()
        .with_ansi(false)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| {
                if settings.production() {
                    "info".into()
                } else {
                    "debug".into()
                }
            }),
        )
        .with_writer(core::logs::LogWriter(logs.clone()))
        .init();
    let state = domain::State::new(settings.clone(), logs).await?;
    if std::env::args().nth(1).as_deref() == Some("check-storage")
        || std::env::args().nth(1).as_deref() == Some("migration-status")
    {
        println!(
            "{}",
            serde_json::to_string_pretty(&domain::verification::check(&state).await?)?
        );
        return Ok(());
    }
    let bind = format!(
        "{}:{}",
        if settings.get("HOST").is_empty() {
            "0.0.0.0".to_owned()
        } else {
            settings.get("HOST")
        },
        settings.number("PORT", 8101)
    );
    let listener = tokio::net::TcpListener::bind(&bind).await?;
    tracing::info!(%bind,version=env!("CARGO_PKG_VERSION"),"Asodya gateway ready");
    axum::serve(
        listener,
        presentation::router(state).into_make_service_with_connect_info::<std::net::SocketAddr>(),
    )
    .with_graceful_shutdown(async {
        let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("SIGTERM handler");
        tokio::select! {_=tokio::signal::ctrl_c()=>{},_=term.recv()=>{}}
    })
    .await?;
    Ok(())
}

#[cfg(test)]
mod tests;
