-- Migration 057: feature-flagged LLM refinement fields for generated topics.

ALTER TABLE chat_topics
    ADD COLUMN IF NOT EXISTS raw_label TEXT,
    ADD COLUMN IF NOT EXISTS refined_label TEXT,
    ADD COLUMN IF NOT EXISTS summary TEXT,
    ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS topic_type TEXT,
    ADD COLUMN IF NOT EXISTS refinement_model TEXT,
    ADD COLUMN IF NOT EXISTS refined_at TIMESTAMPTZ;

UPDATE chat_topics
SET raw_label = label
WHERE raw_label IS NULL;

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
