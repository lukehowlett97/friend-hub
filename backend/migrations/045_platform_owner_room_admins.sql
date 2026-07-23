-- Split global ownership from room administration.
-- techlett is the sole platform owner; non-owner admins keep room-level roles.

DO $$
DECLARE
    techlett_user_id UUID;
BEGIN
    SELECT id
    INTO techlett_user_id
    FROM users
    WHERE lower(username) = 'techlett'
    ORDER BY created_at ASC
    LIMIT 1;

    IF techlett_user_id IS NULL THEN
        RAISE NOTICE 'No techlett user found; leaving platform roles unchanged';
        RETURN;
    END IF;

    UPDATE users
    SET role = 'member'::user_role,
        updated_at = NOW()
    WHERE id <> techlett_user_id
      AND role IN ('owner', 'admin');

    UPDATE users
    SET role = 'owner'::user_role,
        updated_at = NOW()
    WHERE id = techlett_user_id;

    UPDATE room_memberships
    SET role = 'admin'
    WHERE user_id <> techlett_user_id
      AND role = 'owner';

    UPDATE room_memberships
    SET role = 'owner'
    WHERE user_id = techlett_user_id
      AND room_id IN (SELECT id FROM rooms WHERE status = 'active');

    INSERT INTO room_memberships (room_id, user_id, role, joined_at)
    SELECT rooms.id, techlett_user_id, 'owner', NOW()
    FROM rooms
    WHERE rooms.status = 'active'
      AND NOT EXISTS (
          SELECT 1
          FROM room_memberships rm
          WHERE rm.room_id = rooms.id
            AND rm.user_id = techlett_user_id
      );
END $$;
