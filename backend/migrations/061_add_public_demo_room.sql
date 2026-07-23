-- Public demo room with temporary guest access.

ALTER TABLE room_settings
    ADD COLUMN IF NOT EXISTS access_mode VARCHAR(24) NOT NULL DEFAULT 'private',
    ADD COLUMN IF NOT EXISTS allow_guest_messages BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS simulation_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS guest_message_max_length INTEGER NOT NULL DEFAULT 500;

INSERT INTO rooms (id, slug, name, status)
VALUES ('00000000-0000-0000-0000-000000000002', 'demo', 'Friend Hub Demo', 'active')
ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, status = 'active';

INSERT INTO room_settings (
    room_id, access_mode, allow_guest_messages, simulation_enabled, guest_message_max_length
)
SELECT id, 'public_demo', TRUE, TRUE, 500
FROM rooms
WHERE slug = 'demo'
ON CONFLICT (room_id) DO UPDATE SET
    access_mode = 'public_demo',
    allow_guest_messages = TRUE,
    simulation_enabled = TRUE,
    guest_message_max_length = 500;

-- Demo personas. These contain no real user data.
INSERT INTO users (
    session_id, id, username, nickname, display_name, role, user_type,
    is_test_user, is_bot, avatar_emoji, display_role
)
VALUES
    ('00000000-0000-0000-0000-000000000101', '00000000-0000-0000-0000-000000000201', 'demo-alex', 'Alex', 'Alex', 'member', 'demo_bot', TRUE, TRUE, '🧭', 'Demo guide'),
    ('00000000-0000-0000-0000-000000000102', '00000000-0000-0000-0000-000000000202', 'demo-riley', 'Riley', 'Riley', 'member', 'demo_bot', TRUE, TRUE, '🌱', 'Demo visitor'),
    ('00000000-0000-0000-0000-000000000103', '00000000-0000-0000-0000-000000000203', 'demo-sam', 'Sam', 'Sam', 'member', 'demo_bot', TRUE, TRUE, '✨', 'Demo host')
ON CONFLICT (username) DO UPDATE SET user_type = 'demo_bot', is_bot = TRUE, is_test_user = TRUE;

INSERT INTO room_memberships (room_id, user_id, role)
SELECT r.id, u.id, 'member'
FROM rooms r
CROSS JOIN users u
WHERE r.slug = 'demo' AND u.user_type = 'demo_bot'
ON CONFLICT (room_id, user_id) DO NOTHING;

INSERT INTO messages (user_session_id, user_id, content, room_id, created_at)
SELECT u.session_id, u.id, seed.content, r.id, now() - seed.age
FROM (
    VALUES
      ('demo-alex', 'Welcome to the Friend Hub demo — this room is live and safe to explore.', interval '8 minutes'),
      ('demo-riley', 'The real app supports rooms, events, photos, notes, polls, and chat history.', interval '7 minutes'),
      ('demo-sam', 'A visitor can join this room with a temporary name and no account.', interval '6 minutes'),
      ('demo-alex', 'Try sending a message and watch it appear for everyone currently visiting.', interval '5 minutes'),
      ('demo-riley', 'This conversation is simulated; private rooms are kept separate.', interval '4 minutes')
) AS seed(username, content, age)
JOIN users u ON u.username = seed.username
JOIN rooms r ON r.slug = 'demo'
WHERE NOT EXISTS (
    SELECT 1 FROM messages m
    WHERE m.room_id = r.id AND m.user_id = u.id AND m.content = seed.content
);
