-- Migration 034: add image embedding foundation for Messenger-imported photos.

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN undefined_file OR feature_not_supported OR insufficient_privilege THEN
        RAISE NOTICE 'pgvector extension is unavailable or cannot be enabled; using TEXT embedding fallback';
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension setup failed (%); using TEXT embedding fallback', SQLERRM;
END $$;

ALTER TABLE photos
    ADD COLUMN IF NOT EXISTS source_type VARCHAR(64) NOT NULL DEFAULT 'manual_upload',
    ADD COLUMN IF NOT EXISTS source_id UUID,
    ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(80),
    ADD COLUMN IF NOT EXISTS message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS import_batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS storage_path TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS file_size_bytes INTEGER,
    ADD COLUMN IF NOT EXISTS taken_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW();

UPDATE photos
SET storage_path = '/uploads/photos/' || filename
WHERE storage_path = '' AND filename IS NOT NULL;

UPDATE photos
SET file_size_bytes = size_bytes
WHERE file_size_bytes IS NULL AND size_bytes IS NOT NULL;

DO $$
BEGIN
    IF to_regtype('vector') IS NOT NULL THEN
        EXECUTE $ddl$
        CREATE TABLE IF NOT EXISTS photo_embeddings (
            id SERIAL PRIMARY KEY,
            photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            embedding vector(512) NOT NULL,
            caption TEXT,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_photo_embedding_model UNIQUE (photo_id, model_name, model_version)
        )
        $ddl$;
    ELSE
        CREATE TABLE IF NOT EXISTS photo_embeddings (
            id SERIAL PRIMARY KEY,
            photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            model_version TEXT NOT NULL,
            embedding TEXT NOT NULL,
            caption TEXT,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_photo_embedding_model UNIQUE (photo_id, model_name, model_version)
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS photo_embedding_jobs (
    id SERIAL PRIMARY KEY,
    photo_id INTEGER NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_photo_embedding_jobs_status CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'skipped'))
);

CREATE INDEX IF NOT EXISTS idx_photos_message_id ON photos(message_id);
CREATE INDEX IF NOT EXISTS idx_photos_conversation_id ON photos(conversation_id);
CREATE INDEX IF NOT EXISTS idx_photos_import_batch_id ON photos(import_batch_id);
CREATE INDEX IF NOT EXISTS idx_photo_embedding_jobs_status ON photo_embedding_jobs(status);
CREATE INDEX IF NOT EXISTS idx_photo_embedding_jobs_photo_id ON photo_embedding_jobs(photo_id);
CREATE INDEX IF NOT EXISTS idx_photo_embeddings_photo_id ON photo_embeddings(photo_id);

-- Add an ivfflat cosine index after enough embeddings exist to tune the lists
-- parameter for the dataset size, for example:
-- CREATE INDEX CONCURRENTLY idx_photo_embeddings_embedding_cosine
--     ON photo_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
