-- Phase 1: Add room_id column to all room-owned tables.
-- Nullable first; backfill immediately; then make non-null.

DO $$
DECLARE
    default_room_id UUID := '00000000-0000-0000-0000-000000000001';
BEGIN
    -- messages
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='messages' AND column_name='room_id') THEN
        ALTER TABLE messages ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE messages SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE messages ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE messages ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- photos
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='photos' AND column_name='room_id') THEN
        ALTER TABLE photos ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE photos SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE photos ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE photos ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- polls
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='polls' AND column_name='room_id') THEN
        ALTER TABLE polls ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE polls SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE polls ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE polls ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- events
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='events' AND column_name='room_id') THEN
        ALTER TABLE events ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE events SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE events ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE events ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- reminders
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='reminders' AND column_name='room_id') THEN
        ALTER TABLE reminders ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE reminders SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE reminders ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE reminders ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- hub_items
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='hub_items' AND column_name='room_id') THEN
        ALTER TABLE hub_items ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE hub_items SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE hub_items ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE hub_items ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- notifications
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='notifications' AND column_name='room_id') THEN
        ALTER TABLE notifications ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE notifications SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE notifications ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE notifications ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- ai_memory_entries (memories)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='ai_memory_entries' AND column_name='room_id') THEN
        ALTER TABLE ai_memory_entries ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE ai_memory_entries SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE ai_memory_entries ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE ai_memory_entries ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

    -- ideas
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='ideas' AND column_name='room_id') THEN
        ALTER TABLE ideas ADD COLUMN room_id UUID REFERENCES rooms(id) ON DELETE CASCADE;
    END IF;
    UPDATE ideas SET room_id = default_room_id WHERE room_id IS NULL;
    ALTER TABLE ideas ALTER COLUMN room_id SET NOT NULL;
    ALTER TABLE ideas ALTER COLUMN room_id SET DEFAULT '00000000-0000-0000-0000-000000000001';

END;
$$;

-- List-query indexes
CREATE INDEX IF NOT EXISTS idx_messages_room_id      ON messages(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_photos_room_id        ON photos(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_polls_room_id         ON polls(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_room_id        ON events(room_id, starts_at DESC);
CREATE INDEX IF NOT EXISTS idx_reminders_room_id     ON reminders(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hub_items_room_id     ON hub_items(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_room_id ON notifications(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_memory_room_id     ON ai_memory_entries(room_id);
CREATE INDEX IF NOT EXISTS idx_ideas_room_id         ON ideas(room_id, created_at DESC);
