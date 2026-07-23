-- Migration 010: add unified Hub Items foundation.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS hub_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    short_id VARCHAR(20) NOT NULL UNIQUE,
    item_type VARCHAR(24) NOT NULL,
    type_sequence INTEGER NOT NULL,
    title VARCHAR(220) NOT NULL,
    body TEXT,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    pinned_to_home BOOLEAN NOT NULL DEFAULT FALSE,
    sent_to_chat_at TIMESTAMP,
    chat_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_to_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    due_at TIMESTAMP,
    event_start_at TIMESTAMP,
    event_end_at TIMESTAMP,
    source_type VARCHAR(24),
    source_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_hub_item_type_sequence UNIQUE (item_type, type_sequence),
    CONSTRAINT unique_hub_item_source UNIQUE (source_type, source_id)
);

ALTER TABLE IF EXISTS messages
    ADD COLUMN IF NOT EXISTS hub_item_id UUID REFERENCES hub_items(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_hub_items_group_type ON hub_items(group_id, item_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_hub_items_short_id ON hub_items(short_id);
CREATE INDEX IF NOT EXISTS idx_hub_items_pinned ON hub_items(group_id, pinned_to_home, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_hub_items_source ON hub_items(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_messages_hub_item_id ON messages(hub_item_id);

INSERT INTO hub_items (
    group_id, short_id, item_type, type_sequence, title, body, tags, status,
    created_by_user_id, source_type, source_id, created_at, updated_at
)
SELECT
    i.group_id,
    '#I-' || i.id,
    'idea',
    i.id,
    i.title,
    i.description,
    jsonb_build_array(i.category),
    CASE WHEN i.status = 'done' THEN 'done' ELSE 'open' END,
    i.created_by_user_id,
    'idea',
    i.id,
    i.created_at,
    i.updated_at
FROM ideas i
WHERE NOT EXISTS (
    SELECT 1 FROM hub_items h WHERE h.source_type = 'idea' AND h.source_id = i.id
);

INSERT INTO hub_items (
    group_id, short_id, item_type, type_sequence, title, body, tags, status,
    created_by_user_id, due_at, source_type, source_id, created_at, updated_at
)
SELECT
    p.group_id,
    '#P-' || p.id,
    'poll',
    p.id,
    p.question,
    NULL,
    '[]'::jsonb,
    'open',
    p.created_by_user_id,
    p.deadline_at,
    'poll',
    p.id,
    p.created_at,
    p.updated_at
FROM polls p
WHERE NOT EXISTS (
    SELECT 1 FROM hub_items h WHERE h.source_type = 'poll' AND h.source_id = p.id
);

INSERT INTO hub_items (
    group_id, short_id, item_type, type_sequence, title, body, tags, status,
    created_by_user_id, assigned_to_user_id, due_at, source_type, source_id, created_at, updated_at
)
SELECT
    r.group_id,
    '#R-' || r.id,
    'reminder',
    r.id,
    left(r.text, 220),
    r.text,
    '[]'::jsonb,
    CASE WHEN r.is_completed THEN 'done' ELSE 'open' END,
    r.created_by_user_id,
    (
        SELECT ra.user_id
        FROM reminder_assignees ra
        WHERE ra.reminder_id = r.id
        ORDER BY ra.id
        LIMIT 1
    ),
    r.due_at,
    'reminder',
    r.id,
    r.created_at,
    r.updated_at
FROM reminders r
WHERE NOT EXISTS (
    SELECT 1 FROM hub_items h WHERE h.source_type = 'reminder' AND h.source_id = r.id
);

INSERT INTO hub_items (
    group_id, short_id, item_type, type_sequence, title, body, tags, status,
    created_by_user_id, event_start_at, source_type, source_id, created_at, updated_at
)
SELECT
    e.group_id,
    '#E-' || e.id,
    'event',
    e.id,
    e.title,
    e.description,
    '[]'::jsonb,
    'open',
    u.id,
    e.starts_at,
    'event',
    e.id,
    e.created_at,
    e.created_at
FROM events e
LEFT JOIN users u ON u.session_id = e.created_by_session_id
WHERE NOT EXISTS (
    SELECT 1 FROM hub_items h WHERE h.source_type = 'event' AND h.source_id = e.id
);
