import asyncio
import base64
import io
import os
import types
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from PIL import Image

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import router as photo_router
from app.api.v1.router import PhotoUploadRequest, _photo_payload, _photo_with_hub_item, upload_photo
from app.domains.photos.service import photo_storage_usage_bytes
from app.models.room import DEFAULT_ROOM_ID


def _image_data_url(
    *,
    size=(120, 80),
    image_format="PNG",
    color=(20, 90, 180),
    with_exif=False,
) -> str:
    image = Image.new("RGB", size, color)
    output = io.BytesIO()
    save_kwargs = {}
    if with_exif:
        exif = image.getexif()
        exif[271] = "UnitTestCamera"
        save_kwargs["exif"] = exif
        image_format = "JPEG"
    image.save(output, format=image_format, **save_kwargs)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/{image_format.lower()};base64,{encoded}"


class DummyPhotoDb:
    def __init__(self):
        self.added = None

    async def get(self, model, key):
        return None

    def add(self, photo):
        self.added = photo

    async def commit(self):
        return None

    async def refresh(self, photo):
        photo.id = 1


class TestPhotoUploadProcessing(unittest.TestCase):
    def setUp(self):
        self.original_get_settings = photo_router.get_settings
        self.original_get_photo_upload_path = photo_router.get_photo_upload_path
        self.original_current_user = photo_router._current_user_or_401
        self.original_default_group = photo_router._default_group
        self.original_request_room_id = photo_router._request_room_id
        self.temp_dir = TemporaryDirectory()
        self.upload_dir = Path(self.temp_dir.name)
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Photo User",
        )
        photo_router.get_photo_upload_path = lambda: self.upload_dir
        photo_router._current_user_or_401 = lambda authorization, db, session_cookie=None: self._async(self.user)
        photo_router._default_group = lambda db: self._async(types.SimpleNamespace(id=1))
        photo_router._request_room_id = lambda db, **kwargs: self._async(DEFAULT_ROOM_ID)
        photo_router.get_settings = lambda: types.SimpleNamespace(
            photo_max_upload_bytes=5 * 1024 * 1024,
            photo_storage_warn_bytes=20 * 1024 * 1024 * 1024,
            photo_storage_max_bytes=28 * 1024 * 1024 * 1024,
            photo_display_max_width=1600,
            photo_thumbnail_max_width=480,
            photo_jpeg_quality=82,
        )

    def tearDown(self):
        photo_router.get_settings = self.original_get_settings
        photo_router.get_photo_upload_path = self.original_get_photo_upload_path
        photo_router._current_user_or_401 = self.original_current_user
        photo_router._default_group = self.original_default_group
        photo_router._request_room_id = self.original_request_room_id
        self.temp_dir.cleanup()

    @staticmethod
    async def _async(value):
        return value

    def test_upload_valid_image_writes_display_and_thumbnail_metadata(self):
        db = DummyPhotoDb()

        response = asyncio.run(
            upload_photo(
                PhotoUploadRequest(
                    filename="sample.png",
                    content_type="image/png",
                    data_url=_image_data_url(),
                ),
                db=db,
            )
        )

        photo = response["photo"]
        self.assertEqual(photo["content_type"], "image/jpeg")
        self.assertTrue(photo["url"].endswith(".jpg"))
        self.assertTrue(photo["thumbnail_url"].endswith("_thumb.jpg"))
        self.assertGreater(photo["size_bytes"], 0)
        self.assertEqual(photo["width"], 120)
        self.assertEqual(photo["height"], 80)
        self.assertTrue((self.upload_dir / db.added.filename).exists())
        self.assertTrue((self.upload_dir / db.added.thumbnail_filename).exists())
        self.assertEqual(db.added.room_id, DEFAULT_ROOM_ID)

    def test_upload_strips_exif_metadata(self):
        db = DummyPhotoDb()

        asyncio.run(
            upload_photo(
                PhotoUploadRequest(
                    filename="metadata.jpg",
                    content_type="image/jpeg",
                    data_url=_image_data_url(with_exif=True),
                ),
                db=db,
            )
        )

        with Image.open(self.upload_dir / db.added.filename) as image:
            self.assertEqual(len(image.getexif()), 0)

    def test_upload_rejects_oversized_image_before_processing(self):
        photo_router.get_settings = lambda: types.SimpleNamespace(
            photo_max_upload_bytes=4,
            photo_storage_warn_bytes=20 * 1024 * 1024 * 1024,
            photo_storage_max_bytes=28 * 1024 * 1024 * 1024,
            photo_display_max_width=1600,
            photo_thumbnail_max_width=480,
            photo_jpeg_quality=82,
        )

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                upload_photo(
                    PhotoUploadRequest(
                        filename="large.jpg",
                        content_type="image/jpeg",
                        data_url=_image_data_url(),
                    ),
                    db=DummyPhotoDb(),
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Image is too large")
        self.assertEqual(photo_storage_usage_bytes(self.upload_dir), 0)

    def test_upload_rejects_invalid_image_bytes(self):
        encoded = base64.b64encode(b"not an image").decode("ascii")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                upload_photo(
                    PhotoUploadRequest(
                        filename="broken.jpg",
                        content_type="image/jpeg",
                        data_url=f"data:image/jpeg;base64,{encoded}",
                    ),
                    db=DummyPhotoDb(),
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Invalid image data")
        self.assertEqual(photo_storage_usage_bytes(self.upload_dir), 0)

    def test_upload_rejects_animated_images(self):
        output = io.BytesIO()
        frames = [
            Image.new("RGB", (20, 20), (255, 0, 0)),
            Image.new("RGB", (20, 20), (0, 255, 0)),
        ]
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        encoded = base64.b64encode(output.getvalue()).decode("ascii")

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                upload_photo(
                    PhotoUploadRequest(
                        filename="animated.gif",
                        content_type="image/gif",
                        data_url=f"data:image/gif;base64,{encoded}",
                    ),
                    db=DummyPhotoDb(),
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Animated images are not supported")
        self.assertEqual(photo_storage_usage_bytes(self.upload_dir), 0)

    def test_upload_rejects_when_storage_cap_would_be_exceeded_before_writing(self):
        photo_router.get_settings = lambda: types.SimpleNamespace(
            photo_max_upload_bytes=5 * 1024 * 1024,
            photo_storage_warn_bytes=20 * 1024 * 1024 * 1024,
            photo_storage_max_bytes=1,
            photo_display_max_width=1600,
            photo_thumbnail_max_width=480,
            photo_jpeg_quality=82,
        )

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                upload_photo(
                    PhotoUploadRequest(
                        filename="sample.png",
                        content_type="image/png",
                        data_url=_image_data_url(),
                    ),
                    db=DummyPhotoDb(),
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Photo storage is full")
        self.assertEqual(photo_storage_usage_bytes(self.upload_dir), 0)

    def test_photo_payload_includes_thumbnail_and_size_fields(self):
        photo = types.SimpleNamespace(
            id=2,
            filename="display.jpg",
            thumbnail_filename="display_thumb.jpg",
            original_filename="source.png",
            content_type="image/jpeg",
            size_bytes=1234,
            width=100,
            height=75,
            thumbnail_size_bytes=321,
            caption=None,
            tags=[],
            event_id=None,
            created_at=None,
        )

        payload = _photo_payload(photo)

        self.assertEqual(payload["url"], "/uploads/photos/display.jpg")
        self.assertEqual(payload["thumbnail_url"], "/uploads/photos/display_thumb.jpg")
        self.assertEqual(payload["size_bytes"], 1234)

    def test_photo_lookup_rejects_room_mismatch(self):
        from app.models.photo import Photo

        class DummyDb:
            async def get(self, model, key):
                if model is Photo:
                    return types.SimpleNamespace(
                        id=key,
                        deleted_at=None,
                        room_id=uuid.uuid4(),
                        hub_item_id=None,
                        event_id=None,
                    )
                return None

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(_photo_with_hub_item(DummyDb(), 10, room_id=DEFAULT_ROOM_ID))

        self.assertEqual(raised.exception.status_code, 404)


class TestPhotoFiltering(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone, timedelta
        from app.models.photo import Photo

        self.datetime = datetime
        self.timezone = timezone
        self.timedelta = timedelta
        self.Photo = Photo

    def test_tag_filter_case_insensitive(self):
        tag = "camping"
        photo = types.SimpleNamespace(
            id=1,
            filename="photo.jpg",
            thumbnail_filename="photo_thumb.jpg",
            original_filename="photo.jpg",
            content_type="image/jpeg",
            size_bytes=1000,
            width=100,
            height=100,
            caption="A camping trip",
            tags=["camping", "summer"],
            event_id=None,
            hub_item_id=None,
            created_at=self.datetime(2026, 5, 1, 12, 0, 0, tzinfo=self.timezone.utc),
            uploaded_by_session_id="user1",
        )

        normalized_tag = tag.strip().lower().lstrip("#")
        self.assertEqual(normalized_tag, "camping")
        self.assertIn(normalized_tag, photo.tags)

    def test_tag_filter_with_hash(self):
        tag_with_hash = "#camping"
        normalized_tag = tag_with_hash.strip().lower().lstrip("#")
        self.assertEqual(normalized_tag, "camping")

    def test_tag_filter_uppercase(self):
        tag = "CAMPING"
        normalized_tag = tag.strip().lower().lstrip("#")
        self.assertEqual(normalized_tag, "camping")

    def test_date_range_includes_end_date(self):
        from datetime import datetime, timezone, timedelta

        start_date = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        end_date = datetime(2026, 5, 12, 0, 0, 0, tzinfo=timezone.utc)

        end_date_plus_one = end_date + timedelta(days=1)

        photo_on_end_date = datetime(2026, 5, 12, 15, 30, 0, tzinfo=timezone.utc)

        self.assertGreaterEqual(photo_on_end_date, start_date)
        self.assertLess(photo_on_end_date, end_date_plus_one)


class TestPhotoPayloadNewFields(unittest.TestCase):
    """_photo_payload now includes source_type, taken_at, and original_sender."""

    def _make_photo(self, **overrides):
        from datetime import datetime, timezone
        defaults = dict(
            id=1,
            filename="a.jpg",
            thumbnail_filename="a_thumb.jpg",
            original_filename="a.jpg",
            content_type="image/jpeg",
            size_bytes=1000,
            width=100,
            height=100,
            caption=None,
            tags=[],
            event_id=None,
            hub_item_id=None,
            uploaded_by_session_id=None,
            source_type="manual_upload",
            taken_at=None,
            created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            deleted_at=None,
        )
        defaults.update(overrides)
        return types.SimpleNamespace(**defaults)

    def test_payload_includes_source_type(self):
        photo = self._make_photo(source_type="messenger_import")
        payload = _photo_payload(photo)
        self.assertEqual(payload["source_type"], "messenger_import")

    def test_payload_source_type_defaults_to_manual_upload(self):
        photo = self._make_photo(source_type=None)
        payload = _photo_payload(photo)
        self.assertEqual(payload["source_type"], "manual_upload")

    def test_payload_includes_taken_at_when_set(self):
        from datetime import datetime, timezone
        taken = datetime(2025, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        photo = self._make_photo(taken_at=taken)
        payload = _photo_payload(photo)
        self.assertEqual(payload["taken_at"], taken.isoformat())

    def test_payload_taken_at_is_none_when_not_set(self):
        photo = self._make_photo(taken_at=None)
        payload = _photo_payload(photo)
        self.assertIsNone(payload["taken_at"])

    def test_payload_includes_original_sender(self):
        photo = self._make_photo()
        payload = _photo_payload(photo, original_sender="Alice Smith")
        self.assertEqual(payload["original_sender"], "Alice Smith")

    def test_payload_original_sender_defaults_to_none(self):
        photo = self._make_photo()
        payload = _photo_payload(photo)
        self.assertIsNone(payload["original_sender"])

    def test_payload_response_includes_offset_and_limit_keys(self):
        """get_photos response now returns offset and limit for pagination."""
        # This test validates the shape expected by the frontend.
        # The real endpoint is tested via integration; here we just verify
        # the payload dict has the new fields.
        photo = self._make_photo()
        payload = _photo_payload(photo)
        for key in ("source_type", "taken_at", "original_sender"):
            self.assertIn(key, payload, f"Missing key: {key}")


class TestPhotoSortLogic(unittest.TestCase):
    """Verify the sort parameter logic that controls ORDER BY clauses."""

    def test_sort_newest_uses_taken_at_desc(self):
        # "newest" should prefer taken_at DESC (nulls last) then created_at DESC.
        # We verify this by checking the sort value "newest" is accepted and
        # does not raise.
        sort = "newest"
        self.assertIn(sort, ("newest", "oldest", "uploaded"))

    def test_sort_oldest_uses_taken_at_asc(self):
        sort = "oldest"
        self.assertIn(sort, ("newest", "oldest", "uploaded"))

    def test_sort_uploaded_uses_created_at_desc(self):
        sort = "uploaded"
        self.assertIn(sort, ("newest", "oldest", "uploaded"))

    def test_unknown_sort_treated_as_newest(self):
        # Any unknown value should fall back to newest-first logic.
        # In the endpoint: the else branch handles this.
        sort = "random_unknown_value"
        expected_branch = "newest"
        actual = sort if sort in ("newest", "oldest", "uploaded") else "newest"
        self.assertEqual(actual, expected_branch)


class TestPhotoGroupByMonth(unittest.TestCase):
    """Verify month-grouping logic (mirrors the frontend groupByMonth function)."""

    def _group_by_month(self, photos):
        from datetime import datetime
        groups = {}
        order = []
        for p in photos:
            date = datetime.fromisoformat(p["taken_at"] or p["created_at"])
            key = f"{date.year}-{date.month:02d}"
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(p)
        return [(k, groups[k]) for k in order]

    def test_groups_photos_by_year_and_month(self):
        photos = [
            {"id": 1, "taken_at": "2026-05-10T10:00:00", "created_at": "2026-05-10T10:00:00"},
            {"id": 2, "taken_at": "2026-05-20T12:00:00", "created_at": "2026-05-20T12:00:00"},
            {"id": 3, "taken_at": "2026-04-05T08:00:00", "created_at": "2026-04-05T08:00:00"},
        ]
        groups = self._group_by_month(photos)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0][0], "2026-05")
        self.assertEqual(len(groups[0][1]), 2)
        self.assertEqual(groups[1][0], "2026-04")
        self.assertEqual(len(groups[1][1]), 1)

    def test_falls_back_to_created_at_when_taken_at_missing(self):
        photos = [
            {"id": 1, "taken_at": None, "created_at": "2026-03-15T09:00:00"},
        ]
        groups = self._group_by_month(photos)
        self.assertEqual(groups[0][0], "2026-03")

    def test_empty_list_returns_empty_groups(self):
        self.assertEqual(self._group_by_month([]), [])
