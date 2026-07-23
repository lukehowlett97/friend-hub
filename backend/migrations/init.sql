-- Friend Hub Chat Database Schema
-- Version: 1.0.0

-- Enable UUID extension for generating UUIDs
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Drop existing tables if they exist (for clean setup)
DROP TABLE IF EXISTS reactions CASCADE;
DROP TABLE IF EXISTS activity_log CASCADE;
DROP TABLE IF EXISTS comments CASCADE;
DROP TABLE IF EXISTS event_posts CASCADE;
DROP TABLE IF EXISTS reminder_assignees CASCADE;
DROP TABLE IF EXISTS reminders CASCADE;
DROP TABLE IF EXISTS poll_votes CASCADE;
DROP TABLE IF EXISTS poll_options CASCADE;
DROP TABLE IF EXISTS polls CASCADE;
DROP TABLE IF EXISTS ideas CASCADE;
DROP TABLE IF EXISTS hub_items CASCADE;
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS event_invites CASCADE;
DROP TABLE IF EXISTS event_rsvps CASCADE;
DROP TABLE IF EXISTS events CASCADE;
DROP TABLE IF EXISTS photos CASCADE;
DROP TABLE IF EXISTS group_members CASCADE;
DROP TABLE IF EXISTS groups CASCADE;
DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TYPE IF EXISTS activity_action CASCADE;
DROP TYPE IF EXISTS poll_vote_mode CASCADE;
DROP TYPE IF EXISTS idea_status CASCADE;
DROP TYPE IF EXISTS member_role CASCADE;
DROP TYPE IF EXISTS user_role CASCADE;

CREATE TYPE member_role AS ENUM ('owner', 'admin', 'member');
CREATE TYPE user_role AS ENUM ('owner', 'admin', 'member');
CREATE TYPE idea_status AS ENUM ('maybe', 'planned', 'done', 'rejected');
CREATE TYPE poll_vote_mode AS ENUM ('single', 'multiple');
CREATE TYPE activity_action AS ENUM ('created', 'updated', 'deleted', 'voted', 'rsvped', 'completed', 'commented', 'reacted');

-- Users table: Store session information
CREATE TABLE users (
    session_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id UUID NOT NULL UNIQUE DEFAULT uuid_generate_v4(),
    username VARCHAR(50) UNIQUE,
    nickname VARCHAR(50) NOT NULL,
    role user_role NOT NULL DEFAULT 'member',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT true NOT NULL,
    
    CONSTRAINT nickname_length CHECK (LENGTH(TRIM(nickname)) >= 1),
    CONSTRAINT nickname_format CHECK (nickname !~ '^\s*$')
);

-- User sessions table: Store persistent auth sessions for future auth endpoints
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_used_at TIMESTAMP WITH TIME ZONE,
    user_agent VARCHAR(255),
    ip_address VARCHAR(64),
    revoked_at TIMESTAMP WITH TIME ZONE
);

-- Group members table: Store membership role for each user
CREATE TABLE groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    slug VARCHAR(80) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

INSERT INTO groups (name, slug) VALUES ('Friend Hub', 'main');

CREATE TABLE group_members (
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    user_session_id UUID PRIMARY KEY REFERENCES users(session_id) ON DELETE CASCADE,
    role member_role NOT NULL DEFAULT 'member',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Messages table: Store all chat messages
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    user_session_id UUID NOT NULL REFERENCES users(session_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    edited_at TIMESTAMP WITH TIME ZONE,
    is_deleted BOOLEAN DEFAULT false,
    is_imported BOOLEAN DEFAULT false NOT NULL,
    reply_to_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    hub_item_id UUID,

    CONSTRAINT content_not_empty CHECK (LENGTH(TRIM(content)) > 0),
    CONSTRAINT content_max_length CHECK (LENGTH(content) <= 1000)
);

-- Events table: Store lightweight calendar items
CREATE TABLE events (
    id SERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL,
    description TEXT,
    location VARCHAR(160),
    cover_photo_url VARCHAR(500),
    photo_tag_id VARCHAR(40),
    starts_at TIMESTAMP WITH TIME ZONE NOT NULL,
    linked_poll_id INTEGER,
    created_by_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE event_invites (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    invited_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unique_event_invite_user UNIQUE (event_id, user_id)
);

-- Event RSVPs table: Store yes/no responses
CREATE TABLE event_rsvps (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_session_id UUID NOT NULL REFERENCES users(session_id) ON DELETE CASCADE,
    response VARCHAR(8) NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT event_rsvp_response CHECK (response IN ('yes', 'maybe', 'no')),
    CONSTRAINT unique_event_user_rsvp UNIQUE (event_id, user_session_id)
);

CREATE TABLE event_posts (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE ideas (
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

CREATE TABLE polls (
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

ALTER TABLE events ADD CONSTRAINT events_linked_poll_id_fkey FOREIGN KEY (linked_poll_id) REFERENCES polls(id) ON DELETE SET NULL;

CREATE TABLE poll_options (
    id SERIAL PRIMARY KEY,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    label VARCHAR(160) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE poll_votes (
    id SERIAL PRIMARY KEY,
    poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    option_id INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT unique_poll_option_user_vote UNIQUE (poll_id, option_id, user_id)
);

CREATE TABLE reminders (
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

CREATE TABLE reminder_assignees (
    id SERIAL PRIMARY KEY,
    reminder_id INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT unique_reminder_assignee UNIQUE (reminder_id, user_id)
);

CREATE TABLE comments (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    target_type VARCHAR(24) NOT NULL,
    target_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- Photo folders: user-created groups for local uploads
CREATE TABLE photo_folders (
    id SERIAL PRIMARY KEY,
    name VARCHAR(80) NOT NULL UNIQUE,
    created_by_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Photos table: Store local-upload metadata
CREATE TABLE photos (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL UNIQUE,
    thumbnail_filename VARCHAR(255) UNIQUE,
    original_filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(100) NOT NULL,
    size_bytes INTEGER,
    width INTEGER,
    height INTEGER,
    thumbnail_size_bytes INTEGER,
    folder_id INTEGER REFERENCES photo_folders(id) ON DELETE SET NULL,
    event_id INTEGER REFERENCES events(id) ON DELETE SET NULL,
    tag_id VARCHAR(40),
    uploaded_by_session_id UUID REFERENCES users(session_id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Reactions table: Store emoji reactions on messages
CREATE TABLE reactions (
    id SERIAL PRIMARY KEY,
    message_id INTEGER REFERENCES messages(id) ON DELETE CASCADE,
    target_type VARCHAR(24),
    target_id INTEGER,
    user_session_id UUID NOT NULL REFERENCES users(session_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    emoji VARCHAR(10) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    
    -- Ensure one reaction per user per message
    CONSTRAINT unique_user_message_reaction UNIQUE (message_id, user_session_id),
    -- Limit emoji to reasonable length (most are 1-4 characters)
    CONSTRAINT emoji_length CHECK (LENGTH(emoji) <= 10)
);

CREATE TABLE activity_log (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action activity_action NOT NULL,
    target_type VARCHAR(24) NOT NULL,
    target_id INTEGER,
    summary VARCHAR(240) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE hub_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    short_id VARCHAR(20) NOT NULL UNIQUE,
    item_type VARCHAR(24) NOT NULL,
    type_sequence INTEGER NOT NULL,
    title VARCHAR(220) NOT NULL,
    body TEXT,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    pinned_to_home BOOLEAN NOT NULL DEFAULT FALSE,
    sent_to_chat_at TIMESTAMP,
    chat_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    assigned_to_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    due_at TIMESTAMP,
    event_start_at TIMESTAMP,
    event_end_at TIMESTAMP,
    source_type VARCHAR(24),
    source_id INTEGER,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_hub_item_type_sequence UNIQUE (item_type, type_sequence),
    CONSTRAINT unique_hub_item_source UNIQUE (source_type, source_id)
);

ALTER TABLE messages
    ADD CONSTRAINT messages_hub_item_id_fkey
    FOREIGN KEY (hub_item_id) REFERENCES hub_items(id) ON DELETE SET NULL;

-- Indexes for better query performance
CREATE INDEX idx_messages_user_session_id ON messages(user_session_id);
CREATE INDEX idx_messages_user_id ON messages(user_id);
CREATE INDEX idx_messages_created_at ON messages(created_at DESC);
CREATE INDEX idx_messages_reply_to_id ON messages(reply_to_id);
CREATE INDEX idx_events_starts_at ON events(starts_at ASC);
CREATE INDEX idx_events_group_id ON events(group_id);
CREATE INDEX idx_event_invites_event_id ON event_invites(event_id);
CREATE INDEX idx_event_invites_user_id ON event_invites(user_id);
CREATE INDEX idx_event_rsvps_event_id ON event_rsvps(event_id);
CREATE INDEX idx_event_posts_event_created ON event_posts(event_id, created_at DESC);
CREATE INDEX idx_event_posts_group_created ON event_posts(group_id, created_at DESC);
CREATE INDEX idx_ideas_group_status ON ideas(group_id, status);
CREATE INDEX idx_polls_group_created ON polls(group_id, created_at DESC);
CREATE INDEX idx_poll_options_poll_id ON poll_options(poll_id);
CREATE INDEX idx_poll_votes_poll_id ON poll_votes(poll_id);
CREATE INDEX idx_reminders_group_due ON reminders(group_id, due_at);
CREATE INDEX idx_reminder_assignees_reminder_id ON reminder_assignees(reminder_id);
CREATE INDEX idx_comments_target ON comments(target_type, target_id);
CREATE INDEX idx_photos_created_at ON photos(created_at DESC);
CREATE INDEX idx_photos_folder_id ON photos(folder_id);
CREATE INDEX idx_photos_event_id ON photos(event_id);
CREATE INDEX idx_photos_tag_id ON photos(tag_id);
CREATE INDEX idx_reactions_message_id ON reactions(message_id);
CREATE INDEX idx_reactions_target ON reactions(target_type, target_id);
CREATE INDEX idx_reactions_user_session_id ON reactions(user_session_id);
CREATE INDEX idx_reactions_user_id ON reactions(user_id);
CREATE INDEX idx_group_members_role ON group_members(role);
CREATE INDEX idx_group_members_group_id ON group_members(group_id);
CREATE INDEX idx_activity_group_created ON activity_log(group_id, created_at DESC);
CREATE INDEX idx_hub_items_group_type ON hub_items(group_id, item_type, created_at DESC);
CREATE INDEX idx_hub_items_short_id ON hub_items(short_id);
CREATE INDEX idx_hub_items_pinned ON hub_items(group_id, pinned_to_home, updated_at DESC);
CREATE INDEX idx_hub_items_source ON hub_items(source_type, source_id);
CREATE INDEX idx_messages_hub_item_id ON messages(hub_item_id);
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token_hash ON user_sessions(token_hash);
CREATE INDEX idx_users_id ON users(id);
CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_joined_at ON users(joined_at DESC);
CREATE INDEX idx_users_last_seen ON users(last_seen DESC);
CREATE INDEX idx_users_last_seen_at ON users(last_seen_at DESC);

-- Sample data for testing (optional - comment out in production)
INSERT INTO users (session_id, username, nickname, role) VALUES 
    ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'TestUser1', 'TestUser1', 'owner'),
    ('b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12', 'TestUser2', 'TestUser2', 'member');

INSERT INTO group_members (group_id, user_session_id, role) VALUES
    ((SELECT id FROM groups WHERE slug = 'main'), 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'owner'),
    ((SELECT id FROM groups WHERE slug = 'main'), 'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12', 'member');

INSERT INTO messages (user_session_id, content) VALUES
    ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 'Hello, this is a test message!'),
    ('b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12', 'Hi there! Testing the chat app.');

INSERT INTO reactions (message_id, user_session_id, emoji) VALUES
    (1, 'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12', '👍'),
    (2, 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', '😊');

UPDATE reactions SET target_type = 'message', target_id = message_id;

-- Grant permissions (adjust as needed for your setup)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;
