-- Migration 025: Add AI Memory and Suggestions tables for Hub Memory feature.
--
-- These tables implement a local-first Hermes-style memory system:
-- - ai_memory_entries: persistent memory storage (summaries, decisions, preferences)
-- - ai_suggestions: AI-generated suggestions that can be accepted/rejected

-- AI Memory Entries table
CREATE TABLE IF NOT EXISTS ai_memory_entries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_type     VARCHAR(50) NOT NULL,  -- daily_summary, weekly_summary, decision, unresolved_plan, funny_moment, user_preference, suggestion_context
    title           VARCHAR(220),
    content         TEXT NOT NULL,
    source_type     VARCHAR(50),           -- chat, hub_item, manual
    source_id       UUID,                  -- Reference to source entity (e.g., hub_item.id)
    confidence      FLOAT,                 -- 0.0 to 1.0 confidence score
    tags            JSONB NOT NULL DEFAULT '[]',
    created_by      VARCHAR(50) NOT NULL DEFAULT 'hub_bot',
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- AI Suggestions table
CREATE TABLE IF NOT EXISTS ai_suggestions (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suggestion_type       VARCHAR(50) NOT NULL,  -- poll, event, reminder, idea, tag, summary
    title                 VARCHAR(220) NOT NULL,
    body                  TEXT,
    status                VARCHAR(24) NOT NULL DEFAULT 'pending',  -- pending, accepted, rejected, archived
    proposed_hub_item_type VARCHAR(24),         -- idea, poll, reminder, event, note
    proposed_payload      JSONB,                -- Structured payload for creating Hub Item
    source_memory_ids     JSONB NOT NULL DEFAULT '[]',  -- List of AIMemoryEntry IDs (as strings)
    created_hub_item_id   UUID REFERENCES hub_items(id) ON DELETE SET NULL,
    created_at            TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for ai_memory_entries
CREATE INDEX IF NOT EXISTS idx_ai_memory_entries_memory_type ON ai_memory_entries(memory_type);
CREATE INDEX IF NOT EXISTS idx_ai_memory_entries_source ON ai_memory_entries(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_ai_memory_entries_created_at ON ai_memory_entries(created_at DESC);
DROP INDEX IF EXISTS idx_ai_memory_entries_tags;
CREATE INDEX idx_ai_memory_entries_tags ON ai_memory_entries USING GIN(tags);

-- Indexes for ai_suggestions
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_status ON ai_suggestions(status);
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_type ON ai_suggestions(suggestion_type);
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_created_at ON ai_suggestions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_suggestions_hub_item ON ai_suggestions(created_hub_item_id);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_ai_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for updated_at
DROP TRIGGER IF EXISTS trigger_ai_memory_entries_updated_at ON ai_memory_entries;
CREATE TRIGGER trigger_ai_memory_entries_updated_at
    BEFORE UPDATE ON ai_memory_entries
    FOR EACH ROW
    EXECUTE FUNCTION update_ai_updated_at();

DROP TRIGGER IF EXISTS trigger_ai_suggestions_updated_at ON ai_suggestions;
CREATE TRIGGER trigger_ai_suggestions_updated_at
    BEFORE UPDATE ON ai_suggestions
    FOR EACH ROW
    EXECUTE FUNCTION update_ai_updated_at();