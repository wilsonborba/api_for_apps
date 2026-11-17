-- Schema only. Administrators add app plans and feature rows through the API.
CREATE TABLE IF NOT EXISTS public.app_plans (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    code VARCHAR(64) NOT NULL CHECK (length(trim(code)) BETWEEN 1 AND 64),
    name VARCHAR(160) NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 160),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 2048),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (NOT is_active OR code = 'free'),
    UNIQUE (app_id, code),
    UNIQUE (id, app_id)
);
CREATE TABLE IF NOT EXISTS public.app_features (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    code VARCHAR(64) NOT NULL CHECK (length(trim(code)) BETWEEN 1 AND 64),
    name VARCHAR(160) NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 160),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 2048),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (app_id, code),
    UNIQUE (id, app_id)
);
CREATE TABLE IF NOT EXISTS public.plan_features (
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    plan_id VARCHAR(64) NOT NULL,
    feature_id VARCHAR(64) NOT NULL,
    PRIMARY KEY (plan_id, feature_id),
    FOREIGN KEY (plan_id, app_id) REFERENCES public.app_plans(id, app_id) ON DELETE CASCADE,
    FOREIGN KEY (feature_id, app_id) REFERENCES public.app_features(id, app_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS app_plans_app_active_idx ON public.app_plans(app_id, is_active);
CREATE INDEX IF NOT EXISTS app_features_app_active_idx ON public.app_features(app_id, is_active);
CREATE INDEX IF NOT EXISTS plan_features_feature_idx ON public.plan_features(feature_id);
