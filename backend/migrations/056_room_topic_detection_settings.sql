-- Migration 056: room-specific topic detection overrides and v2 generation type.

CREATE TABLE IF NOT EXISTS room_topic_detection_settings (
    room_id UUID PRIMARY KEY REFERENCES rooms(id) ON DELETE CASCADE,
    enabled BOOLEAN,
    similarity_threshold DOUBLE PRECISION,
    hard_gap_minutes INTEGER,
    soft_gap_minutes INTEGER,
    max_topic_duration_hours INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_room_topic_detection_settings_room_id
    ON room_topic_detection_settings(room_id);

ALTER TABLE chat_topics
    DROP CONSTRAINT IF EXISTS ck_chat_topics_generation_type;

ALTER TABLE chat_topics
    ADD CONSTRAINT ck_chat_topics_generation_type
    CHECK (generation_type IN ('semantic_cluster', 'semantic_time_cluster'));
