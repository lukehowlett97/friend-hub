-- Migration 046: Add optional reminder context for LLM-generated reminder messages.

ALTER TABLE reminders
    ADD COLUMN IF NOT EXISTS context TEXT;
