-- Migration 030: Link imported messages to imported identity records.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS imported_identity_id UUID REFERENCES imported_identities(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_messages_imported_identity_id ON messages(imported_identity_id);
