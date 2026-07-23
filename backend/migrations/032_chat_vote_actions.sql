-- Migration 032: Chat governance vote actions.
-- Adds a reusable governance vote-action foundation. Nickname change is the
-- first supported action type; future action types can reuse these tables.

CREATE TABLE IF NOT EXISTS chat_vote_actions (
    id SERIAL PRIMARY KEY,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    target_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action_type VARCHAR(40) NOT NULL,
    status VARCHAR(24) NOT NULL DEFAULT 'open',
    title VARCHAR(160) NOT NULL,
    summary TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    threshold_type VARCHAR(40) NOT NULL,
    threshold_value INTEGER NOT NULL,
    yes_count INTEGER NOT NULL DEFAULT 0,
    no_count INTEGER NOT NULL DEFAULT 0,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    resolved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    resolved_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    open_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    result_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL,
    CONSTRAINT chat_vote_actions_action_type_check CHECK (
        action_type IN (
            'nickname_change',
            'display_role_change',
            'restriction_apply',
            'restriction_remove',
            'rule_create',
            'rule_repeal',
            'council_motion'
        )
    ),
    CONSTRAINT chat_vote_actions_status_check CHECK (
        status IN ('open', 'passed', 'failed', 'expired', 'cancelled')
    ),
    CONSTRAINT chat_vote_actions_threshold_type_check CHECK (
        threshold_type IN ('active_member_majority')
    ),
    CONSTRAINT chat_vote_actions_threshold_value_positive CHECK (threshold_value > 0),
    CONSTRAINT chat_vote_actions_counts_non_negative CHECK (yes_count >= 0 AND no_count >= 0)
);

CREATE TABLE IF NOT EXISTS chat_vote_ballots (
    id SERIAL PRIMARY KEY,
    vote_action_id INTEGER NOT NULL REFERENCES chat_vote_actions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    vote VARCHAR(8) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT chat_vote_ballots_vote_check CHECK (vote IN ('yes', 'no')),
    CONSTRAINT chat_vote_ballots_unique_user_vote UNIQUE (vote_action_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_vote_actions_group_status
    ON chat_vote_actions(group_id, status);

CREATE INDEX IF NOT EXISTS idx_chat_vote_actions_expires_at
    ON chat_vote_actions(expires_at)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_chat_vote_actions_target_user
    ON chat_vote_actions(target_user_id);

CREATE INDEX IF NOT EXISTS idx_chat_vote_ballots_vote_action
    ON chat_vote_ballots(vote_action_id);
