-- Allow admins to pin chat messages so they surface in the noticeboard.
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS pinned_by_session_id UUID;

CREATE INDEX IF NOT EXISTS idx_messages_pinned
    ON messages (room_id, pinned_at DESC)
    WHERE is_pinned = TRUE;
