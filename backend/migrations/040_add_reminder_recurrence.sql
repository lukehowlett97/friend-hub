-- Migration 040: Add recurrence and trigger-tracking to reminders.
--
-- recurrence        NULL = one-time, 'daily', 'weekly', 'every_N_days'
-- recurrence_days   Only used when recurrence = 'every_N_days'; stores N (2..365)
-- recurrence_ends_at  NULL = runs forever; set to stop recurring after this date
-- last_triggered_at   Set each time the scheduler fires this reminder
-- notified_at on reminder_assignees — per-user dedup stamp

DO $$
BEGIN
    -- reminders table additions
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'reminders' AND column_name = 'recurrence'
    ) THEN
        ALTER TABLE reminders ADD COLUMN recurrence VARCHAR(20) NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'reminders' AND column_name = 'recurrence_days'
    ) THEN
        ALTER TABLE reminders ADD COLUMN recurrence_days SMALLINT NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'reminders' AND column_name = 'recurrence_ends_at'
    ) THEN
        ALTER TABLE reminders ADD COLUMN recurrence_ends_at TIMESTAMP WITH TIME ZONE NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'reminders' AND column_name = 'last_triggered_at'
    ) THEN
        ALTER TABLE reminders ADD COLUMN last_triggered_at TIMESTAMP WITH TIME ZONE NULL;
    END IF;

    -- reminder_assignees: per-user notification dedup
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'reminder_assignees' AND column_name = 'notified_at'
    ) THEN
        ALTER TABLE reminder_assignees ADD COLUMN notified_at TIMESTAMP WITH TIME ZONE NULL;
    END IF;
END
$$;

-- Index for the scheduler query: due reminders that haven't fired recently
CREATE INDEX IF NOT EXISTS idx_reminders_scheduler
    ON reminders (due_at, is_completed, archived_at)
    WHERE archived_at IS NULL;
