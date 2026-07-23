-- Media: videos and audio_files tables

CREATE TABLE IF NOT EXISTS videos (
    id                  SERIAL PRIMARY KEY,
    filename            VARCHAR(255) NOT NULL UNIQUE,
    thumbnail_filename  VARCHAR(255) UNIQUE,
    original_filename   VARCHAR(255) NOT NULL,
    content_type        VARCHAR(100) NOT NULL DEFAULT 'video/mp4',
    size_bytes          INTEGER,
    duration_seconds    REAL,
    width               INTEGER,
    height              INTEGER,
    source_type         VARCHAR(64) NOT NULL DEFAULT 'manual_upload',
    source_id           UUID,
    conversation_id     VARCHAR(80),
    message_id          INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    import_batch_id     INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    storage_path        TEXT NOT NULL DEFAULT '',
    caption             VARCHAR(500),
    tags                JSONB NOT NULL DEFAULT '[]',
    uploaded_by_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    room_id             UUID REFERENCES rooms(id) ON DELETE CASCADE,
    taken_at            TIMESTAMPTZ,
    deleted_at          TIMESTAMPTZ,
    deleted_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_videos_room_id ON videos(room_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_videos_message_id ON videos(message_id);

CREATE TABLE IF NOT EXISTS audio_files (
    id                  SERIAL PRIMARY KEY,
    filename            VARCHAR(255) NOT NULL UNIQUE,
    original_filename   VARCHAR(255) NOT NULL,
    content_type        VARCHAR(100) NOT NULL DEFAULT 'audio/mpeg',
    size_bytes          INTEGER,
    duration_seconds    REAL,
    source_type         VARCHAR(64) NOT NULL DEFAULT 'messenger_import',
    conversation_id     VARCHAR(80),
    message_id          INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    import_batch_id     INTEGER REFERENCES import_batches(id) ON DELETE SET NULL,
    storage_path        TEXT NOT NULL DEFAULT '',
    uploaded_by_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    room_id             UUID REFERENCES rooms(id) ON DELETE CASCADE,
    taken_at            TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audio_files_room_id ON audio_files(room_id);
CREATE INDEX IF NOT EXISTS idx_audio_files_message_id ON audio_files(message_id);
