-- Schema only. Application registration is an explicit operator command.
CREATE TABLE IF NOT EXISTS public.defaultdb_client_error (
    id BIGSERIAL PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    session_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) REFERENCES public.defaultdb_user(uuid_id),
    route VARCHAR(500) NOT NULL,
    error_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    stack TEXT NOT NULL,
    build_version VARCHAR(80) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS client_error_app_created_idx ON public.defaultdb_client_error(app_id, created_at);
CREATE TABLE IF NOT EXISTS public.defaultdb_usage_session (
    id VARCHAR(64) PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    user_id VARCHAR(64) REFERENCES public.defaultdb_user(uuid_id),
    started_at TIMESTAMPTZ NOT NULL,
    user_agent VARCHAR(500) NOT NULL,
    ip VARCHAR(45) NOT NULL,
    locale VARCHAR(35) NOT NULL,
    theme VARCHAR(32) NOT NULL,
    viewport_width INTEGER NOT NULL CHECK (viewport_width BETWEEN 0 AND 50000),
    viewport_height INTEGER NOT NULL CHECK (viewport_height BETWEEN 0 AND 50000)
);
CREATE INDEX IF NOT EXISTS usage_session_app_started_idx ON public.defaultdb_usage_session(app_id, started_at);
CREATE TABLE IF NOT EXISTS public.defaultdb_usage_event (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_usage_session(id),
    seq BIGINT NOT NULL CHECK (seq >= 0),
    event_type VARCHAR(16) NOT NULL CHECK (event_type IN ('view','click','input','submit','scroll','error_link')),
    screen VARCHAR(160) NOT NULL,
    route VARCHAR(500) NOT NULL,
    path VARCHAR(500) NOT NULL,
    element_id VARCHAR(200) NOT NULL,
    element_label VARCHAR(200) NOT NULL,
    element_path VARCHAR(600) NOT NULL,
    value TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE INDEX IF NOT EXISTS usage_event_session_created_idx ON public.defaultdb_usage_event(session_id, created_at);
