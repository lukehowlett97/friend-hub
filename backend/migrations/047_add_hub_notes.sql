-- Migration 047: room-scoped Hub Notes.

CREATE TABLE IF NOT EXISTS notes (
    id SERIAL PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    group_id INTEGER NULL REFERENCES groups(id) ON DELETE CASCADE,
    room_sequence INTEGER NOT NULL,
    title VARCHAR(220) NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    note_type VARCHAR(32) NOT NULL DEFAULT 'general',
    edit_mode VARCHAR(32) NOT NULL DEFAULT 'owner_only',
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    archived_at TIMESTAMP NULL,
    archived_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_notes_room_sequence UNIQUE (room_id, room_sequence)
);

CREATE TABLE IF NOT EXISTS note_revisions (
    id SERIAL PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    changed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    before_title TEXT,
    after_title TEXT,
    before_body TEXT,
    after_body TEXT,
    before_note_type VARCHAR(32),
    after_note_type VARCHAR(32),
    before_edit_mode VARCHAR(32),
    after_edit_mode VARCHAR(32),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_room_updated ON notes(room_id, archived_at, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_room_type ON notes(room_id, note_type, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_note_revisions_note_created ON note_revisions(note_id, created_at DESC);

-- Existing hub_items uniqueness was global. Add room-local uniqueness for the
-- multi-room app while keeping this migration idempotent for older databases.
ALTER TABLE hub_items DROP CONSTRAINT IF EXISTS unique_hub_item_type_sequence;
ALTER TABLE hub_items DROP CONSTRAINT IF EXISTS unique_hub_item_source;
ALTER TABLE hub_items DROP CONSTRAINT IF EXISTS hub_items_short_id_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_hub_items_room_short_id_ci
    ON hub_items(room_id, upper(short_id));

CREATE UNIQUE INDEX IF NOT EXISTS uq_hub_items_room_type_sequence
    ON hub_items(room_id, item_type, type_sequence);

CREATE UNIQUE INDEX IF NOT EXISTS uq_hub_items_room_source
    ON hub_items(room_id, source_type, source_id)
    WHERE source_type IS NOT NULL AND source_id IS NOT NULL;

ALTER TABLE ai_draft_actions DROP CONSTRAINT IF EXISTS ai_draft_actions_item_type_check;
ALTER TABLE ai_draft_actions
    ADD CONSTRAINT ai_draft_actions_item_type_check
    CHECK (item_type IN ('event', 'poll', 'reminder', 'note'));
