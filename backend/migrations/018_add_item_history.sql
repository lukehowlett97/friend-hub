-- Migration 018: Item edit history tracking.

CREATE TABLE IF NOT EXISTS item_history (
    id SERIAL PRIMARY KEY,
    item_type VARCHAR(24) NOT NULL,
    item_id INTEGER NOT NULL,
    changed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    changes JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_item_history_lookup ON item_history(item_type, item_id, changed_at DESC);
