-- Schema only. Application registration is a separate operation.
CREATE TABLE IF NOT EXISTS public.defaultdb_app (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(160) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);
