-- Migration 003: add minimal group membership roles.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'member_role') THEN
        CREATE TYPE member_role AS ENUM ('owner', 'admin', 'member');
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS group_members (
    user_session_id UUID PRIMARY KEY REFERENCES users(session_id) ON DELETE CASCADE,
    role member_role NOT NULL DEFAULT 'member',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_group_members_role ON group_members(role);

INSERT INTO group_members (user_session_id, role, created_at)
SELECT
    session_id,
    CASE
        WHEN ROW_NUMBER() OVER (ORDER BY joined_at ASC) = 1 THEN 'owner'::member_role
        ELSE 'member'::member_role
    END,
    COALESCE(joined_at, NOW())
FROM users
WHERE NOT EXISTS (
    SELECT 1 FROM group_members gm WHERE gm.user_session_id = users.session_id
);
