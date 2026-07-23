-- Migration 021: generalize photo attachment + cover image.
--
-- Photos can now be attached to any hub_item (event, poll, idea, reminder,
-- note) via photos.hub_item_id. The "cover image" of an item lives on
-- hub_items.cover_photo_id, replacing the per-type cover_photo_url string.
-- The legacy photos.event_id column is retained for back-compat reads but
-- new uploads should populate hub_item_id.

ALTER TABLE photos
    ADD COLUMN IF NOT EXISTS hub_item_id UUID REFERENCES hub_items(id) ON DELETE SET NULL;

ALTER TABLE hub_items
    ADD COLUMN IF NOT EXISTS cover_photo_id INTEGER REFERENCES photos(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_photos_hub_item_id ON photos(hub_item_id);
CREATE INDEX IF NOT EXISTS idx_hub_items_cover_photo_id ON hub_items(cover_photo_id);

-- Backfill photos.hub_item_id from existing event_id.
UPDATE photos p
SET hub_item_id = h.id
FROM hub_items h
WHERE h.source_type = 'event'
  AND h.source_id = p.event_id
  AND p.event_id IS NOT NULL
  AND p.hub_item_id IS NULL;

-- Backfill hub_items.cover_photo_id from each event's cover_photo_url
-- by matching the filename portion of the URL against photos.filename.
UPDATE hub_items h
SET cover_photo_id = p.id
FROM events e, photos p
WHERE h.source_type = 'event'
  AND h.source_id = e.id
  AND e.cover_photo_url IS NOT NULL
  AND e.cover_photo_url LIKE '/uploads/photos/%'
  AND p.filename = substring(e.cover_photo_url FROM '^/uploads/photos/(.*)$')
  AND h.cover_photo_id IS NULL;
