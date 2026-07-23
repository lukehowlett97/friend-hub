-- Repair chat-agenda rows created before agenda bot messages were room-scoped.
-- The poll already carries the correct room_id; make its marker message and
-- hub item mirror match so chat history reloads in the same room.

UPDATE messages AS m
SET room_id = p.room_id
FROM polls AS p
WHERE p.source = 'chat_agenda'
  AND p.open_message_id = m.id
  AND p.room_id IS NOT NULL
  AND m.room_id IS DISTINCT FROM p.room_id;

UPDATE hub_items AS hi
SET room_id = p.room_id
FROM polls AS p
WHERE p.source = 'chat_agenda'
  AND hi.source_type = 'poll'
  AND hi.source_id = p.id
  AND p.room_id IS NOT NULL
  AND hi.room_id IS DISTINCT FROM p.room_id
  AND NOT EXISTS (
      SELECT 1
      FROM hub_items AS existing
      WHERE existing.room_id = p.room_id
        AND existing.source_type = 'poll'
        AND existing.source_id = p.id
        AND existing.id <> hi.id
  );
