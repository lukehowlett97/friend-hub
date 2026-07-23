-- Assign historical media created before room isolation to the original room.
-- Runtime access denies media without an owning room after this migration.

DO $$
DECLARE
    default_room_id UUID := '00000000-0000-0000-0000-000000000001';
BEGIN
    UPDATE photos
    SET room_id = default_room_id
    WHERE room_id IS NULL;

    UPDATE videos
    SET room_id = default_room_id
    WHERE room_id IS NULL;

    UPDATE audio_files
    SET room_id = default_room_id
    WHERE room_id IS NULL;
END;
$$;
