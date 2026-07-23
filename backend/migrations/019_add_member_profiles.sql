-- Migration 019: Phase 1 of Chat Council — member profile metadata.
-- Adds playful display_role (separate from access role), free-form bio,
-- and an avatar emoji fallback for users without an uploaded avatar.
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS bio TEXT,
  ADD COLUMN IF NOT EXISTS display_role VARCHAR(64),
  ADD COLUMN IF NOT EXISTS avatar_emoji VARCHAR(8);
