-- Migration 014: replace folder system with caption + tags on photos.
ALTER TABLE photos ADD COLUMN IF NOT EXISTS caption VARCHAR(500);
ALTER TABLE photos ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb;
