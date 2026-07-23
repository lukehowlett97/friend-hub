-- Migration 036: soft-delete support for photos
-- Keeps photo metadata in DB after deletion for admin archive view

ALTER TABLE photos
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS deleted_by_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL;
