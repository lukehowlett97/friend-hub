-- Notification preferences per user
-- Users can opt out of specific notification types and control push delivery

CREATE TABLE IF NOT EXISTS notification_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    chat_messages BOOLEAN NOT NULL DEFAULT FALSE,
    chat_mentions BOOLEAN NOT NULL DEFAULT TRUE,
    polls BOOLEAN NOT NULL DEFAULT TRUE,
    events BOOLEAN NOT NULL DEFAULT TRUE,
    reminders BOOLEAN NOT NULL DEFAULT TRUE,
    comments BOOLEAN NOT NULL DEFAULT TRUE,
    reactions BOOLEAN NOT NULL DEFAULT TRUE,
    hub_bot BOOLEAN NOT NULL DEFAULT TRUE,
    push_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE notification_preferences
    ADD COLUMN IF NOT EXISTS chat_messages BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS chat_mentions BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS polls BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS events BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS reminders BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS comments BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS reactions BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS hub_bot BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS push_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

-- Auto-create preferences row when a user is inserted
CREATE OR REPLACE FUNCTION auto_create_notification_preferences()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM notification_preferences WHERE user_id = NEW.id
    ) THEN
        INSERT INTO notification_preferences (user_id)
        VALUES (NEW.id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Only create trigger if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_auto_create_notification_preferences'
    ) THEN
        CREATE TRIGGER trg_auto_create_notification_preferences
        AFTER INSERT ON users
        FOR EACH ROW
        EXECUTE FUNCTION auto_create_notification_preferences();
    END IF;
END;
$$;
