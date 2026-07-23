-- Migration 055: topic detection foundation over chat embedding batches.
-- Batch 1 stores semantic clusters, not final conversation threads.

CREATE TABLE IF NOT EXISTS chat_topics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT,
    confidence DOUBLE PRECISION,
    label_source TEXT NOT NULL DEFAULT 'keyword_placeholder',
    generation_type TEXT NOT NULL DEFAULT 'semantic_cluster',
    topic_date DATE,
    bucket_start_at TIMESTAMPTZ,
    bucket_end_at TIMESTAMPTZ,
    message_start_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    message_end_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    first_message_at TIMESTAMPTZ,
    last_message_at TIMESTAMPTZ,
    batch_count INTEGER NOT NULL DEFAULT 0,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    detection_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_chat_topics_status CHECK (status IN ('active', 'archived')),
    CONSTRAINT ck_chat_topics_generation_type CHECK (generation_type IN ('semantic_cluster')),
    CONSTRAINT ck_chat_topics_label_source CHECK (label_source IN ('keyword_placeholder', 'llm_refined', 'manual'))
);

CREATE TABLE IF NOT EXISTS chat_topic_segments (
    id SERIAL PRIMARY KEY,
    topic_id UUID NOT NULL REFERENCES chat_topics(id) ON DELETE CASCADE,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    embedding_source_id TEXT NOT NULL,
    message_start_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    message_end_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    score DOUBLE PRECISION,
    excerpt TEXT,
    started_at TIMESTAMPTZ,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_topics_room_id ON chat_topics(room_id);
CREATE INDEX IF NOT EXISTS idx_chat_topics_status ON chat_topics(status);
CREATE INDEX IF NOT EXISTS idx_chat_topics_topic_date ON chat_topics(topic_date);
CREATE INDEX IF NOT EXISTS idx_chat_topics_bucket ON chat_topics(bucket_start_at, bucket_end_at);
CREATE INDEX IF NOT EXISTS idx_chat_topics_message_range ON chat_topics(message_start_id, message_end_id);
CREATE INDEX IF NOT EXISTS idx_chat_topics_detection_scope
    ON chat_topics(room_id, model_name, model_version, detection_version);

CREATE INDEX IF NOT EXISTS idx_chat_topic_segments_topic_id ON chat_topic_segments(topic_id);
CREATE INDEX IF NOT EXISTS idx_chat_topic_segments_room_id ON chat_topic_segments(room_id);
CREATE INDEX IF NOT EXISTS idx_chat_topic_segments_message_range
    ON chat_topic_segments(message_start_id, message_end_id);
