-- Add revoked_at to room_invites for manual revocation support
ALTER TABLE room_invites
    ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;
