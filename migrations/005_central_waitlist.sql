-- Schema only. No seed rows, no copied legacy waitlist data and no deletion.
-- A target is exactly one of: a plan or a feature of the same application
-- (composite foreign keys), or a stated communication-interest code.
CREATE TABLE IF NOT EXISTS public.app_waitlist_entries (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL REFERENCES public.defaultdb_app(id),
    target_type VARCHAR(16) NOT NULL CHECK (target_type IN ('plan', 'feature', 'interest')),
    plan_id VARCHAR(64),
    feature_id VARCHAR(64),
    interest VARCHAR(64) CHECK (interest IS NULL OR length(interest) BETWEEN 1 AND 64),
    email VARCHAR(320) NOT NULL CHECK (length(email) BETWEEN 3 AND 320 AND email = lower(email)),
    user_id VARCHAR(64) REFERENCES public.defaultdb_user(uuid_id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'contacted', 'converted', 'declined')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (target_type = 'plan' AND plan_id IS NOT NULL AND feature_id IS NULL AND interest IS NULL)
        OR (target_type = 'feature' AND feature_id IS NOT NULL AND plan_id IS NULL AND interest IS NULL)
        OR (target_type = 'interest' AND interest IS NOT NULL AND plan_id IS NULL AND feature_id IS NULL)
    ),
    FOREIGN KEY (plan_id, app_id) REFERENCES public.app_plans(id, app_id),
    FOREIGN KEY (feature_id, app_id) REFERENCES public.app_features(id, app_id)
);
-- One entry per application, target and email: repeated sign-ups are no-ops.
CREATE UNIQUE INDEX IF NOT EXISTS app_waitlist_plan_email_key
    ON public.app_waitlist_entries(app_id, plan_id, email) WHERE plan_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS app_waitlist_feature_email_key
    ON public.app_waitlist_entries(app_id, feature_id, email) WHERE feature_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS app_waitlist_interest_email_key
    ON public.app_waitlist_entries(app_id, interest, email) WHERE interest IS NOT NULL;
CREATE INDEX IF NOT EXISTS app_waitlist_app_status_idx
    ON public.app_waitlist_entries(app_id, status, created_at);
