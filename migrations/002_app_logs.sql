-- Schema only. The gateway registers known apps through its explicit sync command.
CREATE TABLE IF NOT EXISTS public.defaultdb_app_log (
    id BIGSERIAL PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    level VARCHAR(8) NOT NULL CHECK (level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS defaultdb_app_log_app_created
    ON public.defaultdb_app_log(app_id, created_at);
