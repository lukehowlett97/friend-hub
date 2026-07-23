-- Migration 030: Give Hub Bot a visible profile identity.

UPDATE users
SET
    avatar_emoji = COALESCE(NULLIF(avatar_emoji, ''), '🤖'),
    display_role = COALESCE(NULLIF(display_role, ''), 'Friendly Assistant'),
    bio = COALESCE(
        NULLIF(bio, ''),
        'I help keep Friend Hub organised by answering mentions, summarising chat, and turning plans into useful hub items.'
    ),
    updated_at = NOW()
WHERE session_id = '00000000-0000-0000-0000-000000000b07'::uuid
   OR id = '00000000-0000-0000-0000-000000000b07'::uuid
   OR lower(coalesce(username, '')) = 'hub_bot';
