-- Migration 26: Add AI Agent Runs table for observability
-- Creates table for tracking LLM interactions with full prompt/response logging

CREATE TABLE IF NOT EXISTS ai_agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Run configuration
    mode VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    model VARCHAR(100),
    
    -- Run status
    status VARCHAR(24) NOT NULL DEFAULT 'running',
    
    -- Input
    user_message TEXT,
    prompt_text TEXT,
    
    -- Output
    raw_response TEXT,
    parsed_response JSONB,
    validation_errors JSONB,
    
    -- Results
    created_memory_ids JSONB,
    created_suggestion_ids JSONB,
    tool_calls JSONB,
    
    -- Performance
    duration_ms INTEGER,
    
    -- Error handling
    error_message TEXT,
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_status ON ai_agent_runs(status);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_mode ON ai_agent_runs(mode);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_provider ON ai_agent_runs(provider);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_created_at ON ai_agent_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_agent_runs_completed_at ON ai_agent_runs(completed_at) WHERE completed_at IS NOT NULL;

-- Comment for documentation
COMMENT ON TABLE ai_agent_runs IS 'Tracks AI agent runs for observability and debugging';
COMMENT ON COLUMN ai_agent_runs.mode IS 'Type of operation: summarize, chat, etc.';
COMMENT ON COLUMN ai_agent_runs.provider IS 'LLM provider: fake, ollama, openrouter';
COMMENT ON COLUMN ai_agent_runs.status IS 'Run status: running, completed, failed';