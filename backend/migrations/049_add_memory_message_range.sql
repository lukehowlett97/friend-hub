-- Message-range metadata on AI memory entries, so summaries can link back to
-- the chat messages they cover (catchup gap queries, timeline jump-to-chat).
ALTER TABLE ai_memory_entries ADD COLUMN IF NOT EXISTS message_start_id integer;
ALTER TABLE ai_memory_entries ADD COLUMN IF NOT EXISTS message_end_id integer;
CREATE INDEX IF NOT EXISTS ix_ai_memory_room_type_range
    ON ai_memory_entries (room_id, memory_type, message_end_id);
