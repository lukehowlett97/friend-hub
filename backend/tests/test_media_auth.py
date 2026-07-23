"""
Tests for the authenticated media serving layer (media_router.py).

Covers:
  - Unauthenticated requests are rejected (401)
  - Room-scoped media (photos, videos, audio) requires room membership
  - Users from a different room cannot access the file (404)
  - Valid room members can access media
  - Path traversal attempts are rejected (404)
  - Avatars are accessible to any authenticated user regardless of room
"""
import asyncio
import os
import types
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException

os.environ.setdefault("DEBUG", "false")
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import media_router as mr


# ── Async helpers ─────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.run(coro)


def _async(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner()


# ── Fakes ─────────────────────────────────────────────────────────────────────

def _user(user_id=None):
    return types.SimpleNamespace(id=user_id or uuid.uuid4())


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDb:
    """Minimal async DB session stub."""
    def __init__(self, room_id_for_file=None, member=True):
        self._room_id = room_id_for_file
        self._member = member

    async def execute(self, _stmt):
        return _FakeResult((self._room_id,) if self._room_id is not None else None)


class _FakeRoomRepo:
    def __init__(self, is_member: bool):
        self._is_member = is_member

    async def is_member(self, room_id, user_id):
        return self._is_member


# ── _safe_file_path ───────────────────────────────────────────────────────────

class TestSafeFilePath(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "photo.jpg").write_bytes(b"x")

    def tearDown(self):
        self.tmp.cleanup()

    def test_safe_filename_resolves_correctly(self):
        result = mr._safe_file_path(self.base, "photo.jpg")
        self.assertEqual(result, (self.base / "photo.jpg").resolve())

    def test_path_traversal_with_dotdot_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            mr._safe_file_path(self.base, "../etc/passwd")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_path_traversal_with_backslash_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            mr._safe_file_path(self.base, "..\\etc\\passwd")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_path_traversal_with_forward_slash_is_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            mr._safe_file_path(self.base, "subdir/../../etc/passwd")
        self.assertEqual(ctx.exception.status_code, 404)


# ── _require_room_member_for_file ─────────────────────────────────────────────

class TestRequireRoomMemberForFile(unittest.TestCase):
    def test_no_room_id_is_denied_by_default(self):
        user = _user()
        db = _FakeDb()
        with self.assertRaises(HTTPException) as ctx:
            run(mr._require_room_member_for_file(user, None, db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_member_of_room_is_allowed(self):
        user = _user()
        room_id = uuid.uuid4()
        db = _FakeDb()
        original = mr.RoomRepository

        class _Repo(_FakeRoomRepo):
            def __init__(self, db):
                super().__init__(is_member=True)

        mr.RoomRepository = _Repo
        try:
            run(mr._require_room_member_for_file(user, room_id, db))
        finally:
            mr.RoomRepository = original

    def test_non_member_gets_404(self):
        user = _user()
        room_id = uuid.uuid4()
        db = _FakeDb()
        original = mr.RoomRepository

        class _Repo(_FakeRoomRepo):
            def __init__(self, db):
                super().__init__(is_member=False)

        mr.RoomRepository = original
        mr.RoomRepository = _Repo
        try:
            with self.assertRaises(HTTPException) as ctx:
                run(mr._require_room_member_for_file(user, room_id, db))
            self.assertEqual(ctx.exception.status_code, 404)
        finally:
            mr.RoomRepository = original


# ── serve_photo ───────────────────────────────────────────────────────────────

class TestServePhoto(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.upload_dir = Path(self.tmp.name)
        self.room_id = uuid.uuid4()
        self.user = _user()
        (self.upload_dir / "test.jpg").write_bytes(b"fake jpeg")

        self._orig_upload_path = mr.get_photo_upload_path
        self._orig_auth = mr._require_auth
        self._orig_room_check = mr._require_room_member_for_file
        mr.get_photo_upload_path = lambda: self.upload_dir

    def tearDown(self):
        mr.get_photo_upload_path = self._orig_upload_path
        mr._require_auth = self._orig_auth
        mr._require_room_member_for_file = self._orig_room_check
        self.tmp.cleanup()

    def test_unauthenticated_request_raises_401(self):
        async def _fail(*args, **kwargs):
            raise HTTPException(status_code=401, detail="Authentication required")

        mr._require_auth = _fail
        db = _FakeDb(room_id_for_file=self.room_id)
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_photo("test.jpg", authorization=None, session_cookie=None, db=db))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_room_member_can_access_photo(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_ok(user, room_id, db):
            pass  # allowed

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_ok
        db = _FakeDb(room_id_for_file=self.room_id)
        response = run(mr.serve_photo("test.jpg", authorization="Bearer tok", session_cookie=None, db=db))
        self.assertEqual(response.status_code, 200)

    def test_non_member_gets_404(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_fail(user, room_id, db):
            raise HTTPException(status_code=404)

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_fail
        db = _FakeDb(room_id_for_file=self.room_id)
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_photo("test.jpg", authorization="Bearer tok", session_cookie=None, db=db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_path_traversal_is_rejected(self):
        async def _ok(*args, **kwargs):
            return self.user

        mr._require_auth = _ok
        db = _FakeDb(room_id_for_file=None)
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_photo("../secret.txt", authorization="Bearer tok", session_cookie=None, db=db))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_missing_file_returns_404(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_ok(user, room_id, db):
            pass

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_ok
        db = _FakeDb(room_id_for_file=None)
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_photo("nonexistent.jpg", authorization="Bearer tok", session_cookie=None, db=db))
        self.assertEqual(ctx.exception.status_code, 404)


# ── serve_avatar ──────────────────────────────────────────────────────────────

class TestServeAvatar(unittest.TestCase):
    """Avatars require auth but NOT room membership."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        # The router derives avatar_dir as get_photo_upload_path().parent / "avatars".
        # So point get_photo_upload_path() at a "photos" subdir so that .parent
        # gives us the tmp root, and "avatars" lives alongside it.
        self.upload_dir = Path(self.tmp.name) / "photos"
        self.upload_dir.mkdir()
        self.avatar_dir = Path(self.tmp.name) / "avatars"
        self.avatar_dir.mkdir()
        (self.avatar_dir / "user123.jpg").write_bytes(b"fake avatar")
        self.user = _user()

        self._orig_upload_path = mr.get_photo_upload_path
        self._orig_auth = mr._require_auth
        mr.get_photo_upload_path = lambda: self.upload_dir

    def tearDown(self):
        mr.get_photo_upload_path = self._orig_upload_path
        mr._require_auth = self._orig_auth
        self.tmp.cleanup()

    def test_unauthenticated_request_raises_401(self):
        async def _fail(*args, **kwargs):
            raise HTTPException(status_code=401, detail="Authentication required")

        mr._require_auth = _fail
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_avatar("user123.jpg", authorization=None, session_cookie=None, db=None))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_authenticated_user_in_any_room_can_access_avatar(self):
        async def _ok(*args, **kwargs):
            return self.user

        mr._require_auth = _ok
        # No room membership check at all — pass db=None to confirm it's not used
        response = run(mr.serve_avatar("user123.jpg", authorization="Bearer tok", session_cookie=None, db=None))
        self.assertEqual(response.status_code, 200)

    def test_path_traversal_is_rejected(self):
        async def _ok(*args, **kwargs):
            return self.user

        mr._require_auth = _ok
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_avatar("../photos/secret.jpg", authorization="Bearer tok", session_cookie=None, db=None))
        self.assertEqual(ctx.exception.status_code, 404)


# ── serve_video ───────────────────────────────────────────────────────────────

class TestServeVideo(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        # video_dir = get_photo_upload_path().parent / "videos"
        self.upload_dir = Path(self.tmp.name) / "photos"
        self.upload_dir.mkdir()
        self.video_dir = Path(self.tmp.name) / "videos"
        self.video_dir.mkdir()
        (self.video_dir / "clip.mp4").write_bytes(b"fake video")
        self.room_id = uuid.uuid4()
        self.user = _user()

        self._orig_upload_path = mr.get_photo_upload_path
        self._orig_auth = mr._require_auth
        self._orig_room_check = mr._require_room_member_for_file
        mr.get_photo_upload_path = lambda: self.upload_dir

    def tearDown(self):
        mr.get_photo_upload_path = self._orig_upload_path
        mr._require_auth = self._orig_auth
        mr._require_room_member_for_file = self._orig_room_check
        self.tmp.cleanup()

    def test_unauthenticated_request_raises_401(self):
        async def _fail(*args, **kwargs):
            raise HTTPException(status_code=401)

        mr._require_auth = _fail
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_video("clip.mp4", authorization=None, session_cookie=None, db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_room_member_can_access_video(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_ok(user, room_id, db):
            pass

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_ok
        response = run(mr.serve_video("clip.mp4", authorization="Bearer tok", session_cookie=None, db=_FakeDb(self.room_id)))
        self.assertEqual(response.status_code, 200)

    def test_non_member_gets_404(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_fail(user, room_id, db):
            raise HTTPException(status_code=404)

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_fail
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_video("clip.mp4", authorization="Bearer tok", session_cookie=None, db=_FakeDb(self.room_id)))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_path_traversal_is_rejected(self):
        async def _ok(*args, **kwargs):
            return self.user

        mr._require_auth = _ok
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_video("../../etc/passwd", authorization="Bearer tok", session_cookie=None, db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 404)


# ── serve_audio ───────────────────────────────────────────────────────────────

class TestServeAudio(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        # audio_dir = get_photo_upload_path().parent / "audio"
        self.upload_dir = Path(self.tmp.name) / "photos"
        self.upload_dir.mkdir()
        self.audio_dir = Path(self.tmp.name) / "audio"
        self.audio_dir.mkdir()
        (self.audio_dir / "track.mp3").write_bytes(b"fake audio")
        self.room_id = uuid.uuid4()
        self.user = _user()

        self._orig_upload_path = mr.get_photo_upload_path
        self._orig_auth = mr._require_auth
        self._orig_room_check = mr._require_room_member_for_file
        mr.get_photo_upload_path = lambda: self.upload_dir

    def tearDown(self):
        mr.get_photo_upload_path = self._orig_upload_path
        mr._require_auth = self._orig_auth
        mr._require_room_member_for_file = self._orig_room_check
        self.tmp.cleanup()

    def test_unauthenticated_request_raises_401(self):
        async def _fail(*args, **kwargs):
            raise HTTPException(status_code=401)

        mr._require_auth = _fail
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_audio("track.mp3", authorization=None, session_cookie=None, db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_room_member_can_access_audio(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_ok(user, room_id, db):
            pass

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_ok
        response = run(mr.serve_audio("track.mp3", authorization="Bearer tok", session_cookie=None, db=_FakeDb(self.room_id)))
        self.assertEqual(response.status_code, 200)

    def test_non_member_gets_404(self):
        async def _ok(*args, **kwargs):
            return self.user

        async def _member_fail(user, room_id, db):
            raise HTTPException(status_code=404)

        mr._require_auth = _ok
        mr._require_room_member_for_file = _member_fail
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_audio("track.mp3", authorization="Bearer tok", session_cookie=None, db=_FakeDb(self.room_id)))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_path_traversal_is_rejected(self):
        async def _ok(*args, **kwargs):
            return self.user

        mr._require_auth = _ok
        with self.assertRaises(HTTPException) as ctx:
            run(mr.serve_audio("../photos/secret.jpg", authorization="Bearer tok", session_cookie=None, db=_FakeDb()))
        self.assertEqual(ctx.exception.status_code, 404)
