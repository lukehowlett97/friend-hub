-- Migration 020: Phase 2 of Chat Council — agenda / live chat events.
-- Extends polls so a chat-created motion (nickname / role / general vote)
-- can be scheduled, go live, and close into the existing Polls section.
ALTER TABLE polls
    ADD COLUMN IF NOT EXISTS event_type VARCHAR(24),
    ADD COLUMN IF NOT EXISTS target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS proposed_nickname VARCHAR(50),
    ADD COLUMN IF NOT EXISTS proposed_role VARCHAR(64),
    ADD COLUMN IF NOT EXISTS voting_opens_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS source VARCHAR(24),
    ADD COLUMN IF NOT EXISTS status VARCHAR(24),
    ADD COLUMN IF NOT EXISTS open_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS result_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_polls_status ON polls(status);
CREATE INDEX IF NOT EXISTS idx_polls_voting_opens_at ON polls(voting_opens_at);
