-- Migration 022: persist the focal point of an item's cover photo so users
-- can pan portrait/landscape covers to the part they want visible.
-- Values are percentages (0-100); 50/50 = centered (the existing CSS default).

ALTER TABLE hub_items
    ADD COLUMN IF NOT EXISTS cover_photo_position_x SMALLINT NOT NULL DEFAULT 50,
    ADD COLUMN IF NOT EXISTS cover_photo_position_y SMALLINT NOT NULL DEFAULT 50;
