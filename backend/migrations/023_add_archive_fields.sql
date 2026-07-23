-- Migration 023: add archive support to hub items and major item types
-- Allows safe deletion by moving items to archive instead of removing permanently

ALTER TABLE hub_items
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS archived_by UUID NULL REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE ideas
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS archived_by UUID NULL REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE polls
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS archived_by UUID NULL REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE reminders
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS archived_by UUID NULL REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE events
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS archived_by UUID NULL REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NULL DEFAULT NOW();
