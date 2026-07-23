ALTER TABLE events ADD COLUMN IF NOT EXISTS photo_tag_id VARCHAR(40);
ALTER TABLE photos ADD COLUMN IF NOT EXISTS event_id INTEGER REFERENCES events(id) ON DELETE SET NULL;
ALTER TABLE photos ADD COLUMN IF NOT EXISTS tag_id VARCHAR(40);

UPDATE events
SET photo_tag_id = hub_items.short_id
FROM hub_items
WHERE events.photo_tag_id IS NULL
  AND hub_items.source_type = 'event'
  AND hub_items.source_id = events.id;

CREATE INDEX IF NOT EXISTS idx_photos_event_id ON photos(event_id);
CREATE INDEX IF NOT EXISTS idx_photos_tag_id ON photos(tag_id);
