-- Store noticeboard/banner text per room instead of globally on groups.

ALTER TABLE room_settings
ADD COLUMN IF NOT EXISTS notice TEXT;

UPDATE room_settings
SET notice = groups.notice,
    updated_at = now()
FROM groups
WHERE room_settings.room_id = '00000000-0000-0000-0000-000000000001'
  AND groups.slug = 'main'
  AND room_settings.notice IS NULL
  AND groups.notice IS NOT NULL;
