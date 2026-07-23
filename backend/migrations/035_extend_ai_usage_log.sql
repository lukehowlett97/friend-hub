-- Migration 035: Extend ai_usage_log with user/group/command context.
ALTER TABLE ai_usage_log
    ADD COLUMN IF NOT EXISTS user_id   UUID        NULL,
    ADD COLUMN IF NOT EXISTS group_id  INTEGER     NULL,
    ADD COLUMN IF NOT EXISTS command   VARCHAR(80) NULL;

CREATE INDEX IF NOT EXISTS idx_ai_usage_log_user    ON ai_usage_log(user_id)    WHERE user_id  IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_usage_log_group   ON ai_usage_log(group_id)   WHERE group_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_usage_log_feature ON ai_usage_log(feature);
