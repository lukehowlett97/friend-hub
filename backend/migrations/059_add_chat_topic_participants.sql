CREATE TABLE IF NOT EXISTS chat_topic_participants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id UUID NOT NULL REFERENCES chat_topics(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    canonical_name TEXT NOT NULL,
    display_name TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    segment_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(topic_id, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_chat_topic_participants_topic
    ON chat_topic_participants(topic_id);

CREATE INDEX IF NOT EXISTS idx_chat_topic_participants_room
    ON chat_topic_participants(room_id);

CREATE INDEX IF NOT EXISTS idx_chat_topic_participants_user
    ON chat_topic_participants(user_id);
