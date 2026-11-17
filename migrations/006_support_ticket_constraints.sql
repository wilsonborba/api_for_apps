-- Constraints only. Existing ticket rows are never deleted or rewritten.
-- Adding each constraint validates every existing row; a violation aborts the
-- transaction. The explicit migration tool reports violations and refuses first.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'support_ticket_source_app_fk'
          AND conrelid = 'public.defaultdb_support_ticket'::regclass
    ) THEN
        ALTER TABLE public.defaultdb_support_ticket
            ADD CONSTRAINT support_ticket_source_app_fk
            FOREIGN KEY (source_app) REFERENCES public.defaultdb_app(id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'support_ticket_status_check'
          AND conrelid = 'public.defaultdb_support_ticket'::regclass
    ) THEN
        ALTER TABLE public.defaultdb_support_ticket
            ADD CONSTRAINT support_ticket_status_check
            CHECK (status IN ('open', 'pending', 'resolved', 'closed'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'support_ticket_user_fk'
          AND conrelid = 'public.defaultdb_support_ticket'::regclass
    ) THEN
        -- No ON DELETE action: the gateway never deletes users, and a user
        -- with tickets cannot be removed silently.
        ALTER TABLE public.defaultdb_support_ticket
            ADD CONSTRAINT support_ticket_user_fk
            FOREIGN KEY (user_id) REFERENCES public.defaultdb_user(uuid_id);
    END IF;
END $$;
