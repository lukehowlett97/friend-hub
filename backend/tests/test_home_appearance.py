import asyncio
import os
import types
import unittest
import uuid

from fastapi import HTTPException

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import router
from app.api.v1.router import (
    HomeAppearanceSetCoverRequest,
    HomeAppearanceUpdateRequest,
    get_home_appearance,
    remove_home_appearance_cover,
    set_home_appearance_cover,
    update_home_appearance,
)
from app.models.home_appearance import HomeAppearance
from app.models.photo import Photo


class FakeDb:
    """Minimal in-memory db that supports just enough of AsyncSession for these tests."""

    def __init__(self, *, appearance=None, photos=None):
        self._appearance = appearance
        self._photos = {p.id: p for p in (photos or [])}
        self.added = []
        self.committed = False

    def add(self, value):
        self.added.append(value)
        if isinstance(value, HomeAppearance) and self._appearance is None:
            self._appearance = value

    async def flush(self):
        if self._appearance is not None and self._appearance.id is None:
            self._appearance.id = 1

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        return None

    async def get(self, model, key):
        if model is Photo:
            return self._photos.get(key)
        return None

    async def execute(self, stmt):
        appearance = self._appearance
        return types.SimpleNamespace(scalar_one_or_none=lambda: appearance)


def _photo(photo_id=10):
    return Photo(
        id=photo_id,
        filename=f"file{photo_id}.jpg",
        thumbnail_filename=f"file{photo_id}_thumb.jpg",
        original_filename=f"file{photo_id}.jpg",
        content_type="image/jpeg",
        size_bytes=1024,
    )


class TestHomeAppearanceEndpoints(unittest.TestCase):
    def setUp(self):
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Luke",
            username="luke",
            role=types.SimpleNamespace(value="owner"),
        )
        self.group = types.SimpleNamespace(id=1)
        self._original_user = router._current_user_or_401
        self._original_group = router._default_group
        router._current_user_or_401 = lambda authorization, db: self._async(self.user)
        router._default_group = lambda db: self._async(self.group)

    def tearDown(self):
        router._current_user_or_401 = self._original_user
        router._default_group = self._original_group

    @staticmethod
    async def _async(value):
        return value

    def test_get_returns_defaults_when_no_record(self):
        response = asyncio.run(get_home_appearance(db=FakeDb()))

        appearance = response["appearance"]
        self.assertIsNone(appearance["cover_photo_id"])
        self.assertIsNone(appearance["cover_photo_url"])
        self.assertEqual(appearance["cover_position_x"], 50)
        self.assertEqual(appearance["cover_position_y"], 50)
        self.assertFalse(appearance["blur_enabled"])

    def test_set_cover_persists_photo_and_resets_position(self):
        photo = _photo(10)
        db = FakeDb(photos=[photo])

        response = asyncio.run(set_home_appearance_cover(
            HomeAppearanceSetCoverRequest(photo_id=10), db=db,
        ))

        self.assertEqual(response["appearance"]["cover_photo_id"], 10)
        self.assertEqual(response["appearance"]["cover_photo_url"], "/uploads/photos/file10.jpg")
        self.assertEqual(response["appearance"]["cover_position_x"], 50)
        self.assertEqual(response["appearance"]["cover_position_y"], 50)
        self.assertTrue(db.committed)

    def test_set_cover_rejects_unknown_photo(self):
        db = FakeDb(photos=[])

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(set_home_appearance_cover(
                HomeAppearanceSetCoverRequest(photo_id=999), db=db,
            ))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_update_persists_position_and_overlay(self):
        existing = HomeAppearance(group_id=1, cover_photo_id=10, cover_position_x=50, cover_position_y=50)
        photo = _photo(10)
        db = FakeDb(appearance=existing, photos=[photo])

        response = asyncio.run(update_home_appearance(
            HomeAppearanceUpdateRequest(cover_position_x=20, cover_position_y=80, overlay_strength=70),
            db=db,
        ))

        self.assertEqual(existing.cover_position_x, 20)
        self.assertEqual(existing.cover_position_y, 80)
        self.assertEqual(existing.overlay_strength, 70)
        self.assertEqual(response["appearance"]["cover_position_x"], 20)
        self.assertEqual(response["appearance"]["cover_position_y"], 80)

    def test_update_clamps_position_values(self):
        existing = HomeAppearance(group_id=1, cover_photo_id=None, cover_position_x=50, cover_position_y=50)
        db = FakeDb(appearance=existing)

        asyncio.run(update_home_appearance(
            HomeAppearanceUpdateRequest(cover_position_x=-30, cover_position_y=250), db=db,
        ))

        self.assertEqual(existing.cover_position_x, 0)
        self.assertEqual(existing.cover_position_y, 100)

    def test_update_rejects_unknown_photo_id(self):
        existing = HomeAppearance(group_id=1, cover_photo_id=None, cover_position_x=50, cover_position_y=50)
        db = FakeDb(appearance=existing, photos=[])

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(update_home_appearance(
                HomeAppearanceUpdateRequest(cover_photo_id=42), db=db,
            ))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_remove_cover_clears_photo(self):
        existing = HomeAppearance(group_id=1, cover_photo_id=10, cover_position_x=20, cover_position_y=80)
        db = FakeDb(appearance=existing, photos=[_photo(10)])

        response = asyncio.run(remove_home_appearance_cover(db=db))

        self.assertIsNone(existing.cover_photo_id)
        self.assertEqual(existing.cover_position_x, 50)
        self.assertEqual(existing.cover_position_y, 50)
        self.assertIsNone(response["appearance"]["cover_photo_id"])

    def test_remove_cover_is_noop_when_already_empty(self):
        db = FakeDb()

        response = asyncio.run(remove_home_appearance_cover(db=db))

        self.assertIsNone(response["appearance"]["cover_photo_id"])


if __name__ == "__main__":
    unittest.main()
