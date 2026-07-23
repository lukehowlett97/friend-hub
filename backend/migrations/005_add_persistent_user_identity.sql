-- Migration 005: introduce stable user identity and persistent sessions.
-- Preserves legacy users.session_id and messages/reactions.user_session_id.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
        CREATE TYPE user_role AS ENUM ('owner', 'admin', 'member');
    END IF;
END $$;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS id UUID,
    ADD COLUMN IF NOT EXISTS username VARCHAR(50),
    ADD COLUMN IF NOT EXISTS role user_role NOT NULL DEFAULT 'member',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

UPDATE users SET id = uuid_generate_v4() WHERE id IS NULL;
UPDATE users SET created_at = COALESCE(joined_at, CURRENT_TIMESTAMP) WHERE created_at IS NULL;
UPDATE users SET updated_at = COALESCE(last_seen, CURRENT_TIMESTAMP) WHERE updated_at IS NULL;
UPDATE users SET last_seen_at = last_seen WHERE last_seen_at IS NULL;

ALTER TABLE users
    ALTER COLUMN id SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL,
    ALTER COLUMN is_active SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_id_unique'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_id_unique UNIQUE (id);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'users_username_unique'
    ) THEN
        ALTER TABLE users ADD CONSTRAINT users_username_unique UNIQUE (username);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_used_at TIMESTAMP WITH TIME ZONE,
    user_agent VARCHAR(255),
    ip_address VARCHAR(64),
    revoked_at TIMESTAMP WITH TIME ZONE
);

DO $$
BEGIN
    IF to_regclass('public.messages') IS NOT NULL THEN
        ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

DO $$
BEGIN
    IF to_regclass('public.reactions') IS NOT NULL THEN
        ALTER TABLE reactions
            ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_token_hash ON user_sessions(token_hash);
DO $$
BEGIN
    IF to_regclass('public.messages') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
    END IF;
    IF to_regclass('public.reactions') IS NOT NULL THEN
        CREATE INDEX IF NOT EXISTS idx_reactions_user_id ON reactions(user_id);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_users_id ON users(id);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_last_seen_at ON users(last_seen_at DESC);
