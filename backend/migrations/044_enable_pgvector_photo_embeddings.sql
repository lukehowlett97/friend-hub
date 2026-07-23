-- Migration 044: require pgvector-backed photo embeddings for vector photo search.

CREATE EXTENSION IF NOT EXISTS vector;

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
);

DO $$
DECLARE
    embedding_type TEXT;
BEGIN
    SELECT format_type(a.atttypid, a.atttypmod)
    INTO embedding_type
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'photo_embeddings'
      AND a.attname = 'embedding'
      AND NOT a.attisdropped;

    IF embedding_type = 'text' THEN
        EXECUTE 'ALTER TABLE photo_embeddings ALTER COLUMN embedding TYPE vector(512) USING embedding::vector(512)';
    END IF;

    SELECT format_type(a.atttypid, a.atttypmod)
    INTO embedding_type
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'photo_embeddings'
      AND a.attname = 'embedding'
      AND NOT a.attisdropped;

    IF embedding_type <> 'vector(512)' THEN
        RAISE EXCEPTION 'photo_embeddings.embedding must be vector(512), found %', embedding_type;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_photo_embeddings_photo_id ON photo_embeddings(photo_id);
