-- Migration 017: Track external imports and source-message idempotency.

CREATE TABLE IF NOT EXISTS import_batches (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(64) NOT NULL,
    source_path TEXT NOT NULL,
    source_thread_path VARCHAR(500),
    target_room_id VARCHAR(80),
    status VARCHAR(24) NOT NULL DEFAULT 'running',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    message_count INTEGER NOT NULL DEFAULT 0,
    imported_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    media_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    imported_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL
);

ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS source_thread_path VARCHAR(500);
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS target_room_id VARCHAR(80);
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS media_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS error_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS errors JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE import_batches ADD COLUMN IF NOT EXISTS imported_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS external_identities (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(64) NOT NULL,
    external_name VARCHAR(255) NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    user_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_external_identity_provider_name UNIQUE (provider, external_name)
);

CREATE TABLE IF NOT EXISTS imported_message_sources (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    provider VARCHAR(64) NOT NULL,
    source_thread_path VARCHAR(500) NOT NULL,
    target_room_id VARCHAR(80),
    source_hash VARCHAR(64) NOT NULL,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    raw_sender_name VARCHAR(255) NOT NULL,
    source_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_imported_message_provider_hash UNIQUE (provider, source_hash)
);

ALTER TABLE imported_message_sources ADD COLUMN IF NOT EXISTS target_room_id VARCHAR(80);
ALTER TABLE imported_message_sources ADD COLUMN IF NOT EXISTS raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_import_batches_provider ON import_batches(provider);
CREATE INDEX IF NOT EXISTS idx_imported_message_sources_message_id ON imported_message_sources(message_id);
CREATE INDEX IF NOT EXISTS idx_imported_message_sources_thread ON imported_message_sources(provider, source_thread_path);
CREATE INDEX IF NOT EXISTS idx_external_identities_user_id ON external_identities(user_id);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS is_imported BOOLEAN NOT NULL DEFAULT false;
