-- Phase 1: Multi-room architecture — core room tables

CREATE TABLE IF NOT EXISTS rooms (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(80)  NOT NULL UNIQUE,
    name        VARCHAR(120) NOT NULL,
    status      VARCHAR(24)  NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS room_memberships (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id     UUID        NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    user_id     UUID        NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    role        VARCHAR(24) NOT NULL DEFAULT 'member',
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (room_id, user_id)
);

CREATE TABLE IF NOT EXISTS room_invites (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id         UUID        NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    created_by_user_id UUID     REFERENCES users(id) ON DELETE SET NULL,
    code            VARCHAR(64) NOT NULL UNIQUE,
    max_uses        INT         NOT NULL DEFAULT 1,
    use_count       INT         NOT NULL DEFAULT 0,
    expires_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS room_settings (
    room_id             UUID PRIMARY KEY REFERENCES rooms(id) ON DELETE CASCADE,
    allow_invites       BOOLEAN NOT NULL DEFAULT TRUE,
    max_members         INT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_room_memberships_room_id  ON room_memberships(room_id);
CREATE INDEX IF NOT EXISTS idx_room_memberships_user_id  ON room_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_room_invites_room_id      ON room_invites(room_id);
CREATE INDEX IF NOT EXISTS idx_room_invites_code         ON room_invites(code);

-- Default room for existing deployments
INSERT INTO rooms (id, slug, name, status)
VALUES ('00000000-0000-0000-0000-000000000001', 'main', 'Main Space', 'active')
ON CONFLICT DO NOTHING;

-- Default room_settings row
INSERT INTO room_settings (room_id)
SELECT '00000000-0000-0000-0000-000000000001'
WHERE NOT EXISTS (
    SELECT 1 FROM room_settings WHERE room_id = '00000000-0000-0000-0000-000000000001'
);

-- Enrol every existing active user as a member of the default room.
-- Users with role owner/admin get room role 'admin'; others get 'member'.
INSERT INTO room_memberships (room_id, user_id, role)
SELECT
    '00000000-0000-0000-0000-000000000001',
    id,
    CASE WHEN role IN ('owner', 'admin') THEN 'admin' ELSE 'member' END
FROM users
WHERE is_active = TRUE
  AND id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM room_memberships rm
      WHERE rm.room_id = '00000000-0000-0000-0000-000000000001'
        AND rm.user_id = users.id
  );

-- The first owner-role user gets room role 'owner'
UPDATE room_memberships
SET role = 'owner'
WHERE room_id = '00000000-0000-0000-0000-000000000001'
  AND user_id = (
      SELECT id FROM users
      WHERE role = 'owner'
        AND is_active = TRUE
        AND id IS NOT NULL
      ORDER BY created_at ASC
      LIMIT 1
  );
