-- Migration 006: add persistent folders for local photos.

CREATE TABLE IF NOT EXISTS photo_folders (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    created_by_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE IF EXISTS photos
    ADD COLUMN IF NOT EXISTS folder_id INTEGER REFERENCES photo_folders(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_photos_folder_id ON photos(folder_id);
