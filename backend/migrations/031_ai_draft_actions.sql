-- Migration 031: Add ai_draft_actions table for AI-proposed Hub Items.
--
-- Draft actions are AI-generated proposals for Events, Polls, and Reminders
-- that only become real app items after explicit user confirmation.
-- The AI may propose (status='draft'); only a user may accept or reject.

CREATE TABLE IF NOT EXISTS ai_draft_actions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Ownership / scoping
    group_id                INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    created_by_user_id      UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,

    -- Who proposed it and what kind of action it is
    proposed_by             VARCHAR(24) NOT NULL DEFAULT 'ai',
    action_type             VARCHAR(50) NOT NULL DEFAULT 'create_hub_item',
    item_type               VARCHAR(24) NOT NULL,

    -- Lifecycle status
    status                  VARCHAR(24) NOT NULL DEFAULT 'draft',

    -- Display fields
    title                   TEXT NOT NULL,
    summary                 TEXT,

    -- Structured payload (type-specific: event/poll/reminder fields as JSON)
    payload_json            JSONB NOT NULL DEFAULT '{}',

    -- Where this draft originated
    source                  VARCHAR(50) NOT NULL DEFAULT 'hub_lab',

    -- Optional back-reference to the chat message that triggered the proposal
    source_message_id       INTEGER REFERENCES messages(id) ON DELETE SET NULL,

    -- Observability: which agent run produced this draft
    agent_run_id            UUID REFERENCES ai_agent_runs(id) ON DELETE SET NULL,

    -- Set on accept: the hub_items mirror row (always created for any item type)
    created_hub_item_id     UUID REFERENCES hub_items(id) ON DELETE SET NULL,

    -- Set on accept: canonical domain rows (only one will be non-null per draft)
    created_poll_id         INTEGER REFERENCES polls(id) ON DELETE SET NULL,
    created_event_id        INTEGER REFERENCES events(id) ON DELETE SET NULL,
    created_reminder_id     INTEGER REFERENCES reminders(id) ON DELETE SET NULL,

    -- Resolution tracking
    resolved_at             TIMESTAMP WITH TIME ZONE,
    resolved_by_user_id     UUID REFERENCES users(id) ON DELETE SET NULL,

    -- Timestamps
    created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT ai_draft_actions_action_type_check
        CHECK (action_type IN ('create_hub_item')),

    CONSTRAINT ai_draft_actions_item_type_check
        CHECK (item_type IN ('event', 'poll', 'reminder')),

    CONSTRAINT ai_draft_actions_status_check
        CHECK (status IN ('draft', 'accepted', 'rejected', 'expired')),

    CONSTRAINT ai_draft_actions_title_not_blank
        CHECK (LENGTH(TRIM(title)) > 0)
);

-- Primary query patterns: list pending drafts for a group, ordered by creation time
CREATE INDEX IF NOT EXISTS idx_ai_draft_actions_group_status_created
    ON ai_draft_actions(group_id, status, created_at DESC);

-- Observability: look up drafts produced by a specific agent run
CREATE INDEX IF NOT EXISTS idx_ai_draft_actions_agent_run_id
    ON ai_draft_actions(agent_run_id)
    WHERE agent_run_id IS NOT NULL;

-- Back-reference from a chat message to any draft it triggered
CREATE INDEX IF NOT EXISTS idx_ai_draft_actions_source_message_id
    ON ai_draft_actions(source_message_id)
    WHERE source_message_id IS NOT NULL;

-- Drafts created by a specific user (for user-facing history views)
CREATE INDEX IF NOT EXISTS idx_ai_draft_actions_created_by_user_id
    ON ai_draft_actions(created_by_user_id);

-- Reuse the trigger function defined in migration 025
DROP TRIGGER IF EXISTS trigger_ai_draft_actions_updated_at ON ai_draft_actions;
CREATE TRIGGER trigger_ai_draft_actions_updated_at
    BEFORE UPDATE ON ai_draft_actions
    FOR EACH ROW
    EXECUTE FUNCTION update_ai_updated_at();

COMMENT ON TABLE ai_draft_actions IS 'AI-proposed Hub Item drafts awaiting user confirmation. The AI may only propose; a user must accept to create the real item.';
COMMENT ON COLUMN ai_draft_actions.payload_json IS 'Type-specific structured payload. Event: {title,description,starts_at,ends_at,location,tags}. Poll: {question,options,vote_mode,closes_at,tags}. Reminder: {text,remind_at,group_wide,target_user_ids,tags}.';
COMMENT ON COLUMN ai_draft_actions.source IS 'Origin of this draft: hub_lab, chat, or scheduled_job.';
COMMENT ON COLUMN ai_draft_actions.created_hub_item_id IS 'Set when accepted: the hub_items mirror row.';
COMMENT ON COLUMN ai_draft_actions.created_poll_id IS 'Set when accepted and item_type=poll: the canonical polls row.';
COMMENT ON COLUMN ai_draft_actions.created_event_id IS 'Set when accepted and item_type=event: the canonical events row.';
COMMENT ON COLUMN ai_draft_actions.created_reminder_id IS 'Set when accepted and item_type=reminder: the canonical reminders row.';
