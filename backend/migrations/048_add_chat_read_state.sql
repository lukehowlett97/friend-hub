-- Per-user, per-room chat read tracking (last message the user has seen).
CREATE TABLE IF NOT EXISTS chat_read_state (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    room_id uuid NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    last_read_message_id integer NOT NULL,
    updated_at timestamp NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, room_id)
);
