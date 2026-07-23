-- Migration 027: admin-created users, invite codes, PIN auth state.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS display_name VARCHAR(64),
    ADD COLUMN IF NOT EXISTS pin_hash VARCHAR(255),
    ADD COLUMN IF NOT EXISTS invite_code_hash VARCHAR(255),
    ADD COLUMN IF NOT EXISTS invite_code_used_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS invite_code_expires_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_until TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP WITH TIME ZONE;

UPDATE users
SET display_name = nickname
WHERE display_name IS NULL;

UPDATE users
SET username = 'legacy_' || REPLACE(session_id::text, '-', '')
WHERE username IS NULL;

ALTER TABLE users
    ALTER COLUMN username DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower_unique
    ON users (LOWER(username));

CREATE INDEX IF NOT EXISTS idx_users_invite_code_expires_at
    ON users(invite_code_expires_at);
