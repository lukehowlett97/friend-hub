-- Migration 028: keep the system Hub Bot account addressable by a stable mention.

UPDATE users
SET
    username = 'hub_bot',
    nickname = 'Hub Bot',
    display_name = 'Hub Bot',
    is_bot = true,
    updated_at = NOW()
WHERE session_id = '00000000-0000-0000-0000-000000000b07'::uuid
   OR id = '00000000-0000-0000-0000-000000000b07'::uuid
   OR username = 'legacy_00000000000000000000000000000b07';
