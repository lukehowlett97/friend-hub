-- Migration 007: Phase 1 friends hub planning schema.

DO $$ BEGIN
    CREATE TYPE idea_status AS ENUM ('maybe', 'planned', 'done', 'rejected');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE poll_vote_mode AS ENUM ('single', 'multiple');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE activity_action AS ENUM ('created', 'updated', 'deleted', 'voted', 'rsvped', 'completed', 'commented', 'reacted');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    slug VARCHAR(80) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

INSERT INTO groups (name, slug, created_at)
SELECT 'Friend Hub', 'main', NOW()
WHERE NOT EXISTS (
    SELECT 1 FROM groups existing WHERE existing.slug = 'main'
);

ALTER TABLE group_members ADD COLUMN IF NOT EXISTS group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE;
UPDATE group_members SET group_id = (SELECT id FROM groups WHERE slug = 'main') WHERE group_id IS NULL;

ALTER TABLE events ADD COLUMN IF NOT EXISTS group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS location VARCHAR(160);
ALTER TABLE events ADD COLUMN IF NOT EXISTS linked_poll_id INTEGER;
ALTER TABLE event_rsvps ALTER COLUMN response TYPE VARCHAR(8);
ALTER TABLE event_rsvps DROP CONSTRAINT IF EXISTS event_rsvp_response;
ALTER TABLE event_rsvps ADD CONSTRAINT event_rsvp_response CHECK (response IN ('yes', 'maybe', 'no'));
UPDATE events SET group_id = (SELECT id FROM groups WHERE slug = 'main') WHERE group_id IS NULL;

CREATE TABLE IF NOT EXISTS ideas (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    title VARCHAR(160) NOT NULL,
    description TEXT,
    category VARCHAR(60) NOT NULL DEFAULT 'general',
    status idea_status NOT NULL DEFAULT 'maybe',
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS polls (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    question VARCHAR(220) NOT NULL,
    vote_mode poll_vote_mode NOT NULL DEFAULT 'single',
    deadline_at TIMESTAMP WITH TIME ZONE,
    linked_idea_id INTEGER REFERENCES ideas(id) ON DELETE SET NULL,
    linked_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

DO $$ BEGIN
    ALTER TABLE events ADD CONSTRAINT events_linked_poll_id_fkey
        FOREIGN KEY (linked_poll_id) REFERENCES polls(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS poll_options (
    id SERIAL PRIMARY KEY,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    label VARCHAR(160) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id SERIAL PRIMARY KEY,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unique_poll_option_user_vote UNIQUE (poll_id, option_id, user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    context TEXT,
    due_at TIMESTAMP WITH TIME ZONE,
    linked_event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
    is_completed BOOLEAN DEFAULT false NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    completed_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS reminder_assignees (
    id SERIAL PRIMARY KEY,
    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT unique_reminder_assignee UNIQUE (reminder_id, user_id)
);

CREATE TABLE IF NOT EXISTS comments (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    target_type VARCHAR(24) NOT NULL,
    target_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

ALTER TABLE reactions ADD COLUMN IF NOT EXISTS target_type VARCHAR(24);
ALTER TABLE reactions ADD COLUMN IF NOT EXISTS target_id INTEGER;
ALTER TABLE reactions ALTER COLUMN message_id DROP NOT NULL;
UPDATE reactions SET target_type = 'message', target_id = message_id WHERE target_type IS NULL AND message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action activity_action NOT NULL,
    target_type VARCHAR(24) NOT NULL,
    target_id INTEGER,
    summary VARCHAR(240) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_events_group_id ON events(group_id);
CREATE INDEX IF NOT EXISTS idx_ideas_group_status ON ideas(group_id, status);
CREATE INDEX IF NOT EXISTS idx_polls_group_created ON polls(group_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_poll_options_poll_id ON poll_options(poll_id);
CREATE INDEX IF NOT EXISTS idx_poll_votes_poll_id ON poll_votes(poll_id);
CREATE INDEX IF NOT EXISTS idx_reminders_group_due ON reminders(group_id, due_at);
CREATE INDEX IF NOT EXISTS idx_reminder_assignees_reminder_id ON reminder_assignees(reminder_id);
CREATE INDEX IF NOT EXISTS idx_comments_target ON comments(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_reactions_target ON reactions(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_activity_group_created ON activity_log(group_id, created_at DESC);
