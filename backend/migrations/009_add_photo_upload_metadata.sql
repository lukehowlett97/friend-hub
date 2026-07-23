-- Migration 009: add processed photo metadata and thumbnail references.

ALTER TABLE IF EXISTS photos
    ADD COLUMN IF NOT EXISTS thumbnail_filename VARCHAR(255),
    ADD COLUMN IF NOT EXISTS size_bytes INTEGER,
    ADD COLUMN IF NOT EXISTS width INTEGER,
    ADD COLUMN IF NOT EXISTS height INTEGER,
    ADD COLUMN IF NOT EXISTS thumbnail_size_bytes INTEGER;

CREATE UNIQUE INDEX IF NOT EXISTS idx_photos_thumbnail_filename
    ON photos(thumbnail_filename)
    WHERE thumbnail_filename IS NOT NULL;
