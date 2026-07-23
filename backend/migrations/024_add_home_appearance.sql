-- Migration 024: store homepage appearance settings (cover image, position,
-- overlay strength, blur, header icon) per group.
--
-- One row per group (enforced via UNIQUE(group_id)). Defaults match the
-- existing clean default header so an absent row renders the same as a
-- row with all NULLs / defaults.

CREATE TABLE IF NOT EXISTS home_appearance (
    id              SERIAL PRIMARY KEY,
    group_id        INTEGER NOT NULL UNIQUE
                    REFERENCES groups(id) ON DELETE CASCADE,
    cover_photo_id  INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    cover_position_x SMALLINT NOT NULL DEFAULT 50,
    cover_position_y SMALLINT NOT NULL DEFAULT 50,
    overlay_strength SMALLINT NOT NULL DEFAULT 50,
    blur_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
    header_icon     VARCHAR(40),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_home_appearance_group_id ON home_appearance(group_id);
CREATE INDEX IF NOT EXISTS idx_home_appearance_cover_photo_id ON home_appearance(cover_photo_id);
