-- Migration 052: chat embeddings foundation for semantic search (Slice B).
-- Embeds message batches, memory entries, summaries, and hub items.
-- Mirrors the photo embeddings pattern (034/044) including the TEXT fallback
-- when pgvector is unavailable.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN undefined_file OR feature_not_supported OR insufficient_privilege THEN
        RAISE NOTICE 'pgvector extension is unavailable or cannot be enabled; using TEXT embedding fallback';
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension setup failed (%); using TEXT embedding fallback', SQLERRM;
END $$;

DO $$
BEGIN
    IF to_regtype('vector') IS NOT NULL THEN
        EXECUTE $ddl$
        CREATE TABLE IF NOT EXISTS chat_embeddings (
            id SERIAL PRIMARY KEY,
            source_type TEXT NOT NULL,            -- message_batch | memory | summary | hub_item
            source_id TEXT NOT NULL,
            room_id UUID REFERENCES rooms(id) ON DELETE CASCADE,
            message_start_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
            message_end_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            -- dimensionless: dimension varies by embedding model; queries must
            -- always filter model_name/model_version so <=> never mixes dims
            embedding vector NOT NULL,
            content_preview TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_chat_embedding_source_model UNIQUE (source_type, source_id, model_name, model_version)
        )
        $ddl$;
    ELSE
        CREATE TABLE IF NOT EXISTS chat_embeddings (
            id SERIAL PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            room_id UUID REFERENCES rooms(id) ON DELETE CASCADE,
            message_start_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
            message_end_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            embedding TEXT NOT NULL,
            content_preview TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_chat_embedding_source_model UNIQUE (source_type, source_id, model_name, model_version)
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS chat_embedding_jobs (
    id SERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    room_id UUID REFERENCES rooms(id) ON DELETE CASCADE,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"message_start_id": .., "message_end_id": ..} for message_batch
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_chat_embedding_job_source UNIQUE (source_type, source_id),
    CONSTRAINT ck_chat_embedding_jobs_status CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_chat_embedding_jobs_status ON chat_embedding_jobs(status);
CREATE INDEX IF NOT EXISTS idx_chat_embeddings_room_id ON chat_embeddings(room_id);
CREATE INDEX IF NOT EXISTS idx_chat_embeddings_source_type ON chat_embeddings(source_type);
CREATE INDEX IF NOT EXISTS idx_chat_embeddings_message_end_id ON chat_embeddings(message_end_id);

-- Exact scan is fine at this scale (k <= 8). A cosine ivfflat index requires a
-- fixed dimension, so revisit only if a single model is locked in and volume grows.
