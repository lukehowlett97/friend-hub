-- Migration 058: room-scoped canonical participant aliases for private topic refinement exports.

CREATE TABLE IF NOT EXISTS room_participant_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_room_participant_aliases_display_name_not_blank CHECK (length(trim(display_name)) > 0),
    CONSTRAINT ck_room_participant_aliases_canonical_name_not_blank CHECK (length(trim(canonical_name)) > 0),
    CONSTRAINT uq_room_participant_aliases_room_display UNIQUE (room_id, display_name)
);

CREATE INDEX IF NOT EXISTS idx_room_participant_aliases_room_id
    ON room_participant_aliases(room_id);

ALTER TABLE chat_topics
    DROP CONSTRAINT IF EXISTS ck_chat_topics_topic_type;

ALTER TABLE chat_topics
    ADD CONSTRAINT ck_chat_topics_topic_type
    CHECK (
        topic_type IS NULL
        OR topic_type IN (
            'planning',
            'general_chat',
            'event',
            'sport',
            'gaming',
            'food_drink',
            'music',
            'travel',
            'work',
            'relationship',
            'memory',
            'unknown'
        )
    );
