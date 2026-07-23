-- Showcase data for the public demo room. These rows are deliberately labelled
-- and are kept isolated from the main room by room_id.

DO $$
DECLARE
    demo_room UUID := '00000000-0000-0000-0000-000000000002';
    demo_user UUID := '00000000-0000-0000-0000-000000000203';
    demo_session UUID := '00000000-0000-0000-0000-000000000103';
    group_key INTEGER;
    event_key INTEGER;
    reminder_key INTEGER;
    next_sequence INTEGER;
BEGIN
    SELECT id INTO group_key FROM groups ORDER BY id LIMIT 1;

    event_key := NULL;
    INSERT INTO events (group_id, room_id, title, description, location, starts_at, created_by_session_id)
    SELECT group_key, demo_room, '[Demo] Community Picnic',
           'A sample event showing how shared plans appear in Friend Hub.',
           'Riverside Park', now() + interval '2 days', demo_session
    WHERE NOT EXISTS (
        SELECT 1 FROM events WHERE room_id = demo_room AND title = '[Demo] Community Picnic'
    )
    RETURNING id INTO event_key;

    IF event_key IS NULL THEN
        SELECT id INTO event_key FROM events WHERE room_id = demo_room AND title = '[Demo] Community Picnic' LIMIT 1;
    END IF;

    SELECT COALESCE(MAX(type_sequence), 0) + 1 INTO next_sequence
    FROM hub_items WHERE room_id = demo_room AND item_type = 'event';
    INSERT INTO hub_items (group_id, room_id, short_id, item_type, type_sequence, title, body,
                           tags, status, source_type, source_id, created_by_user_id, event_start_at)
    SELECT group_key, demo_room, '#E-' || event_key, 'event', next_sequence,
           '[Demo] Community Picnic', 'A sample event showing how shared plans appear in Friend Hub.',
           '["demo"]'::jsonb, 'open', 'event', event_key, demo_user, now() + interval '2 days'
    WHERE NOT EXISTS (
        SELECT 1 FROM hub_items WHERE room_id = demo_room AND source_type = 'event' AND source_id = event_key
    );

    event_key := NULL;
    INSERT INTO events (group_id, room_id, title, description, location, starts_at, created_by_session_id)
    SELECT group_key, demo_room, '[Demo] Game Night',
           'Bring a favourite game and meet the demo room visitors.',
           'Friend Hub Lounge', now() + interval '5 days', demo_session
    WHERE NOT EXISTS (
        SELECT 1 FROM events WHERE room_id = demo_room AND title = '[Demo] Game Night'
    )
    RETURNING id INTO event_key;

    IF event_key IS NULL THEN
        SELECT id INTO event_key FROM events WHERE room_id = demo_room AND title = '[Demo] Game Night' LIMIT 1;
    END IF;

    SELECT COALESCE(MAX(type_sequence), 0) + 1 INTO next_sequence
    FROM hub_items WHERE room_id = demo_room AND item_type = 'event';
    INSERT INTO hub_items (group_id, room_id, short_id, item_type, type_sequence, title, body,
                           tags, status, source_type, source_id, created_by_user_id, event_start_at)
    SELECT group_key, demo_room, '#E-' || event_key, 'event', next_sequence,
           '[Demo] Game Night', 'Bring a favourite game and meet the demo room visitors.',
           '["demo"]'::jsonb, 'open', 'event', event_key, demo_user, now() + interval '5 days'
    WHERE NOT EXISTS (
        SELECT 1 FROM hub_items WHERE room_id = demo_room AND source_type = 'event' AND source_id = event_key
    );

    event_key := NULL;
    INSERT INTO events (group_id, room_id, title, description, location, starts_at, created_by_session_id)
    SELECT group_key, demo_room, '[Demo] Photo Walk',
           'A sample event for trying RSVPs and shared planning.',
           'Old Town Market', now() + interval '9 days', demo_session
    WHERE NOT EXISTS (
        SELECT 1 FROM events WHERE room_id = demo_room AND title = '[Demo] Photo Walk'
    )
    RETURNING id INTO event_key;

    IF event_key IS NULL THEN
        SELECT id INTO event_key FROM events WHERE room_id = demo_room AND title = '[Demo] Photo Walk' LIMIT 1;
    END IF;

    SELECT COALESCE(MAX(type_sequence), 0) + 1 INTO next_sequence
    FROM hub_items WHERE room_id = demo_room AND item_type = 'event';
    INSERT INTO hub_items (group_id, room_id, short_id, item_type, type_sequence, title, body,
                           tags, status, source_type, source_id, created_by_user_id, event_start_at)
    SELECT group_key, demo_room, '#E-' || event_key, 'event', next_sequence,
           '[Demo] Photo Walk', 'A sample event for trying RSVPs and shared planning.',
           '["demo"]'::jsonb, 'open', 'event', event_key, demo_user, now() + interval '9 days'
    WHERE NOT EXISTS (
        SELECT 1 FROM hub_items WHERE room_id = demo_room AND source_type = 'event' AND source_id = event_key
    );

    reminder_key := NULL;
    INSERT INTO reminders (group_id, room_id, text, context, due_at, created_by_user_id, linked_event_id)
    SELECT group_key, demo_room, 'Pack a picnic blanket', 'Sample demo reminder', now() + interval '1 day', demo_user,
           (SELECT id FROM events WHERE room_id = demo_room AND title = '[Demo] Community Picnic' LIMIT 1)
    WHERE NOT EXISTS (
        SELECT 1 FROM reminders WHERE room_id = demo_room AND text = 'Pack a picnic blanket'
    )
    RETURNING id INTO reminder_key;

    IF reminder_key IS NULL THEN
        SELECT id INTO reminder_key FROM reminders WHERE room_id = demo_room AND text = 'Pack a picnic blanket' LIMIT 1;
    END IF;
    SELECT COALESCE(MAX(type_sequence), 0) + 1 INTO next_sequence FROM hub_items WHERE room_id = demo_room AND item_type = 'reminder';
    INSERT INTO hub_items (group_id, room_id, short_id, item_type, type_sequence, title, body, tags, status,
                           source_type, source_id, created_by_user_id, due_at)
    SELECT group_key, demo_room, '#R-' || reminder_key, 'reminder', next_sequence, 'Pack a picnic blanket',
           'Sample demo reminder', '["demo"]'::jsonb, 'open', 'reminder', reminder_key, demo_user, now() + interval '1 day'
    WHERE NOT EXISTS (
        SELECT 1 FROM hub_items WHERE room_id = demo_room AND source_type = 'reminder' AND source_id = reminder_key
    );

    reminder_key := NULL;
    INSERT INTO reminders (group_id, room_id, text, context, due_at, created_by_user_id)
    SELECT group_key, demo_room, 'Choose a game to bring', 'Sample demo reminder', now() + interval '4 days', demo_user
    WHERE NOT EXISTS (
        SELECT 1 FROM reminders WHERE room_id = demo_room AND text = 'Choose a game to bring'
    )
    RETURNING id INTO reminder_key;

    IF reminder_key IS NULL THEN
        SELECT id INTO reminder_key FROM reminders WHERE room_id = demo_room AND text = 'Choose a game to bring' LIMIT 1;
    END IF;
    SELECT COALESCE(MAX(type_sequence), 0) + 1 INTO next_sequence FROM hub_items WHERE room_id = demo_room AND item_type = 'reminder';
    INSERT INTO hub_items (group_id, room_id, short_id, item_type, type_sequence, title, body, tags, status,
                           source_type, source_id, created_by_user_id, due_at)
    SELECT group_key, demo_room, '#R-' || reminder_key, 'reminder', next_sequence, 'Choose a game to bring',
           'Sample demo reminder', '["demo"]'::jsonb, 'open', 'reminder', reminder_key, demo_user, now() + interval '4 days'
    WHERE NOT EXISTS (
        SELECT 1 FROM hub_items WHERE room_id = demo_room AND source_type = 'reminder' AND source_id = reminder_key
    );

    reminder_key := NULL;
    INSERT INTO reminders (group_id, room_id, text, context, due_at, created_by_user_id)
    SELECT group_key, demo_room, 'Charge your camera', 'Sample demo reminder', now() + interval '8 days', demo_user
    WHERE NOT EXISTS (
        SELECT 1 FROM reminders WHERE room_id = demo_room AND text = 'Charge your camera'
    )
    RETURNING id INTO reminder_key;

    IF reminder_key IS NULL THEN
        SELECT id INTO reminder_key FROM reminders WHERE room_id = demo_room AND text = 'Charge your camera' LIMIT 1;
    END IF;
    SELECT COALESCE(MAX(type_sequence), 0) + 1 INTO next_sequence FROM hub_items WHERE room_id = demo_room AND item_type = 'reminder';
    INSERT INTO hub_items (group_id, room_id, short_id, item_type, type_sequence, title, body, tags, status,
                           source_type, source_id, created_by_user_id, due_at)
    SELECT group_key, demo_room, '#R-' || reminder_key, 'reminder', next_sequence, 'Charge your camera',
           'Sample demo reminder', '["demo"]'::jsonb, 'open', 'reminder', reminder_key, demo_user, now() + interval '8 days'
    WHERE NOT EXISTS (
        SELECT 1 FROM hub_items WHERE room_id = demo_room AND source_type = 'reminder' AND source_id = reminder_key
    );
END
$$;
