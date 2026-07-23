-- Migration 016: Add is_bot flag to users and insert Hub Bot system user.
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_bot BOOLEAN NOT NULL DEFAULT false;

INSERT INTO users (session_id, id, username, nickname, role, is_bot, is_active, updated_at)
VALUES (
    '00000000-0000-0000-0000-000000000b07'::uuid,
    '00000000-0000-0000-0000-000000000b07'::uuid,
    'hub_bot',
    'Hub Bot',
    'member',
    true,
    true,
    NOW()
) ON CONFLICT DO NOTHING;
