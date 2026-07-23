-- Migration 015: AI API usage tracking table.
CREATE TABLE IF NOT EXISTS ai_usage_log (
    id          SERIAL PRIMARY KEY,
    provider    VARCHAR(40) NOT NULL DEFAULT 'anthropic',
    model       VARCHAR(80),
    feature     VARCHAR(80),
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_cents  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_log_created ON ai_usage_log(created_at DESC);
