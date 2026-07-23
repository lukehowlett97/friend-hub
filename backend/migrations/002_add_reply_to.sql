-- Migration 002: add reply_to_id to messages
-- Run this against an existing database that was created before this column existed.
-- Safe to run multiple times (uses IF NOT EXISTS / IF EXISTS guards).

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS reply_to_id INTEGER REFERENCES messages(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_messages_reply_to_id ON messages(reply_to_id);
