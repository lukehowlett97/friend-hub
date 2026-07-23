-- Migration 029: Member cleanup and imported identity foundation.

CREATE TABLE IF NOT EXISTS imported_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL DEFAULT 'messenger',
    source_participant_id TEXT,
    source_display_name TEXT NOT NULL,
    normalised_name TEXT NOT NULL,
    linked_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'unlinked',
    message_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    confidence_score DOUBLE PRECISION,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_imported_identities_source ON imported_identities(source);
CREATE INDEX IF NOT EXISTS idx_imported_identities_normalised_name ON imported_identities(normalised_name);
CREATE INDEX IF NOT EXISTS idx_imported_identities_linked_user_id ON imported_identities(linked_user_id);
CREATE INDEX IF NOT EXISTS idx_imported_identities_status ON imported_identities(status);
CREATE INDEX IF NOT EXISTS idx_imported_identities_source_display_name ON imported_identities(source, source_display_name);
CREATE INDEX IF NOT EXISTS idx_imported_identities_source_normalised_name ON imported_identities(source, normalised_name);

ALTER TABLE users ADD COLUMN IF NOT EXISTS user_type TEXT NOT NULL DEFAULT 'human';
ALTER TABLE users ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_test_user BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hidden_from_member_list BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMP;

UPDATE users
SET
    user_type = 'bot',
    is_bot = true,
    hidden_from_member_list = true,
    updated_at = NOW()
WHERE session_id = '00000000-0000-0000-0000-000000000b07'::uuid
   OR id = '00000000-0000-0000-0000-000000000b07'::uuid
   OR lower(coalesce(username, '')) = 'hub_bot'
   OR lower(coalesce(nickname, '')) = 'hub bot'
   OR lower(coalesce(display_name, '')) = 'hub bot';

UPDATE users
SET
    status = CASE WHEN is_active THEN 'active' ELSE 'deactivated' END,
    deactivated_at = CASE WHEN is_active THEN deactivated_at ELSE coalesce(deactivated_at, updated_at, NOW()) END
WHERE status IS NULL OR status = '';
