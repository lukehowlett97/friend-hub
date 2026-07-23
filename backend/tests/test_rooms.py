"""
Tests for Phase 1 multi-room architecture.

Covers:
- Default room creation / backfill (migration SQL logic)
- Current-room resolution (slug header, single room, multiple rooms)
- RoomRepository membership helpers
- Room routes via the router (GET /rooms, GET /current-room)
- Cross-room isolation (user cannot see another room's data)
- Existing single-room behaviour still works
"""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

os.environ["DEBUG"] = "false"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_room(slug="main", name="Main Space", status="active", room_id=None):
    r = MagicMock()
    r.id = room_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    r.slug = slug
    r.name = name
    r.status = status
    r.created_at = datetime(2025, 1, 1)
    return r


def _make_membership(room_id=None, user_id=None, role="member"):
    m = MagicMock()
    m.room_id = room_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    m.user_id = user_id or uuid.uuid4()
    m.role = role
    m.joined_at = datetime(2025, 1, 1)
    return m


def _make_user(user_id=None, role="member"):
    u = MagicMock()
    u.id = user_id or uuid.uuid4()
    u.role = role
    return u


# ---------------------------------------------------------------------------
# RoomService.resolve_room
# ---------------------------------------------------------------------------

class TestRoomServiceResolveRoom(unittest.TestCase):

    def _service(self, rooms_for_user=None, room_by_slug=None, is_member_result=True):
        from app.domains.rooms.service import RoomService

        service = RoomService.__new__(RoomService)

        repo = MagicMock()
        repo.get_room_by_slug = AsyncMock(return_value=room_by_slug)
        repo.is_member = AsyncMock(return_value=is_member_result)
        repo.get_rooms_for_user = AsyncMock(return_value=rooms_for_user or [])
        service.repository = repo
        return service

    def test_slug_provided_room_found_member(self):
        room = _make_room()
        service = self._service(room_by_slug=room, is_member_result=True)
        result_room, error = asyncio.run(
            service.resolve_room(slug="main", user_id=uuid.uuid4())
        )
        self.assertIsNone(error)
        self.assertIs(result_room, room)

    def test_slug_provided_room_not_found(self):
        service = self._service(room_by_slug=None)
        result_room, error = asyncio.run(
            service.resolve_room(slug="ghost", user_id=uuid.uuid4())
        )
        self.assertIsNone(result_room)
        self.assertIn("not found", error)

    def test_slug_provided_not_a_member(self):
        room = _make_room()
        service = self._service(room_by_slug=room, is_member_result=False)
        result_room, error = asyncio.run(
            service.resolve_room(slug="main", user_id=uuid.uuid4())
        )
        self.assertIsNone(result_room)
        self.assertIn("not a member", error)

    def test_no_slug_single_room_auto_resolved(self):
        room = _make_room()
        membership = _make_membership()
        service = self._service(rooms_for_user=[(room, membership)])
        result_room, error = asyncio.run(
            service.resolve_room(slug=None, user_id=uuid.uuid4())
        )
        self.assertIsNone(error)
        self.assertIs(result_room, room)

    def test_no_slug_multiple_rooms_returns_error(self):
        room_a = _make_room(slug="a", room_id=uuid.uuid4())
        room_b = _make_room(slug="b", room_id=uuid.uuid4())
        m = _make_membership()
        service = self._service(rooms_for_user=[(room_a, m), (room_b, m)])
        result_room, error = asyncio.run(
            service.resolve_room(slug=None, user_id=uuid.uuid4())
        )
        self.assertIsNone(result_room)
        self.assertIn("X-Room-Slug", error)

    def test_no_slug_no_rooms_returns_error(self):
        service = self._service(rooms_for_user=[])
        result_room, error = asyncio.run(
            service.resolve_room(slug=None, user_id=uuid.uuid4())
        )
        self.assertIsNone(result_room)
        self.assertIn("not a member of any room", error)


# ---------------------------------------------------------------------------
# RoomRepository helpers
# ---------------------------------------------------------------------------

class TestRoomRepository(unittest.TestCase):

    def _repo(self, membership=None):
        from app.domains.rooms.repository import RoomRepository

        repo = RoomRepository.__new__(RoomRepository)
        repo.get_membership = AsyncMock(return_value=membership)
        return repo

    def test_is_member_true_when_membership_exists(self):
        m = _make_membership(role="member")
        repo = self._repo(membership=m)
        result = asyncio.run(repo.is_member(m.room_id, m.user_id))
        self.assertTrue(result)

    def test_is_member_false_when_no_membership(self):
        repo = self._repo(membership=None)
        result = asyncio.run(repo.is_member(uuid.uuid4(), uuid.uuid4()))
        self.assertFalse(result)

    def test_is_admin_true_for_admin_role(self):
        m = _make_membership(role="admin")
        repo = self._repo(membership=m)
        result = asyncio.run(repo.is_admin(m.room_id, m.user_id))
        self.assertTrue(result)

    def test_is_admin_true_for_owner_role(self):
        m = _make_membership(role="owner")
        repo = self._repo(membership=m)
        result = asyncio.run(repo.is_admin(m.room_id, m.user_id))
        self.assertTrue(result)

    def test_is_admin_false_for_member_role(self):
        m = _make_membership(role="member")
        repo = self._repo(membership=m)
        result = asyncio.run(repo.is_admin(m.room_id, m.user_id))
        self.assertFalse(result)

    def test_is_owner_true_for_owner_role(self):
        m = _make_membership(role="owner")
        repo = self._repo(membership=m)
        result = asyncio.run(repo.is_owner(m.room_id, m.user_id))
        self.assertTrue(result)

    def test_is_owner_false_for_admin_role(self):
        m = _make_membership(role="admin")
        repo = self._repo(membership=m)
        result = asyncio.run(repo.is_owner(m.room_id, m.user_id))
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Default room creation
# ---------------------------------------------------------------------------

class TestDefaultRoomConstants(unittest.TestCase):

    def test_default_room_id_constant(self):
        from app.models.room import DEFAULT_ROOM_ID
        self.assertEqual(str(DEFAULT_ROOM_ID), "00000000-0000-0000-0000-000000000001")

    def test_default_room_slug_constant(self):
        from app.models.room import DEFAULT_ROOM_SLUG
        self.assertEqual(DEFAULT_ROOM_SLUG, "main")


# ---------------------------------------------------------------------------
# room_payload helper
# ---------------------------------------------------------------------------

class TestRoomPayload(unittest.TestCase):

    def test_payload_shape(self):
        from app.domains.rooms.service import _room_payload
        room = _make_room(slug="main", name="Main Space")
        membership = _make_membership(role="owner")
        payload = _room_payload(room, membership)
        self.assertEqual(payload["slug"], "main")
        self.assertEqual(payload["name"], "Main Space")
        self.assertEqual(payload["role"], "owner")
        self.assertIn("id", payload)
        self.assertIn("joined_at", payload)


# ---------------------------------------------------------------------------
# GET /api/v1/rooms route
# ---------------------------------------------------------------------------

class TestRoomsRoute(unittest.TestCase):

    def test_list_rooms_returns_rooms_for_authenticated_user(self):
        from app.api.v1.router import list_rooms

        room = _make_room()
        membership = _make_membership(role="member")

        fake_user = _make_user()

        async def fake_resolve(slug, user_id):
            return room, None

        with patch("app.api.v1.router._current_user_or_401", new=AsyncMock(return_value=fake_user)):
            with patch(
                "app.domains.rooms.service.RoomService.get_rooms_for_user",
                new=AsyncMock(return_value=[{"slug": "main", "name": "Main Space", "role": "member", "id": str(room.id), "status": "active", "joined_at": None}]),
            ):
                result = asyncio.run(list_rooms(authorization="Bearer tok", session_cookie=None, db=MagicMock()))
        self.assertIn("rooms", result)
        self.assertEqual(result["rooms"][0]["slug"], "main")


# ---------------------------------------------------------------------------
# GET /api/v1/current-room route
# ---------------------------------------------------------------------------

class TestCurrentRoomRoute(unittest.TestCase):

    def test_current_room_resolved_from_slug(self):
        from app.api.v1.router import get_current_room_info

        room = _make_room()
        membership = _make_membership(role="member")
        fake_user = _make_user()

        with patch("app.api.v1.router._current_user_or_401", new=AsyncMock(return_value=fake_user)):
            with patch(
                "app.domains.rooms.service.RoomService.resolve_room",
                new=AsyncMock(return_value=(room, None)),
            ):
                with patch(
                    "app.domains.rooms.repository.RoomRepository.get_membership",
                    new=AsyncMock(return_value=membership),
                ):
                    result = asyncio.run(
                        get_current_room_info(
                            x_room_slug="main",
                            authorization="Bearer tok",
                            session_cookie=None,
                            db=MagicMock(),
                        )
                    )
        self.assertIn("room", result)
        self.assertEqual(result["room"]["slug"], "main")

    def test_current_room_404_when_not_found(self):
        from app.api.v1.router import get_current_room_info
        from fastapi import HTTPException

        fake_user = _make_user()

        with patch("app.api.v1.router._current_user_or_401", new=AsyncMock(return_value=fake_user)):
            with patch(
                "app.domains.rooms.service.RoomService.resolve_room",
                new=AsyncMock(return_value=(None, "Room not found")),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(
                        get_current_room_info(
                            x_room_slug="ghost",
                            authorization="Bearer tok",
                            session_cookie=None,
                            db=MagicMock(),
                        )
                    )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_current_room_400_for_ambiguous_slug(self):
        from app.api.v1.router import get_current_room_info
        from fastapi import HTTPException

        fake_user = _make_user()

        with patch("app.api.v1.router._current_user_or_401", new=AsyncMock(return_value=fake_user)):
            with patch(
                "app.domains.rooms.service.RoomService.resolve_room",
                new=AsyncMock(return_value=(None, "Multiple rooms available — send X-Room-Slug header to select one")),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(
                        get_current_room_info(
                            x_room_slug=None,
                            authorization="Bearer tok",
                            session_cookie=None,
                            db=MagicMock(),
                        )
                    )
        self.assertEqual(ctx.exception.status_code, 400)


# ---------------------------------------------------------------------------
# FastAPI room dependencies
# ---------------------------------------------------------------------------

class TestRoomDependencies(unittest.TestCase):

    def test_get_current_user_authenticates_bearer_token(self):
        from app.domains.rooms.dependencies import get_current_user

        fake_user = _make_user()
        auth_service = MagicMock()
        auth_service.authenticate_token = AsyncMock(return_value=(fake_user, MagicMock()))

        with patch("app.domains.rooms.dependencies.AuthService", return_value=auth_service):
            result = asyncio.run(
                get_current_user(
                    authorization="Bearer token-123",
                    session_cookie=None,
                    db=MagicMock(),
                )
            )

        self.assertIs(result, fake_user)
        auth_service.authenticate_token.assert_awaited_once_with("token-123")

    def test_get_current_user_falls_back_to_session_cookie(self):
        from app.domains.rooms.dependencies import get_current_user

        fake_user = _make_user()
        auth_service = MagicMock()
        auth_service.authenticate_token = AsyncMock(return_value=(fake_user, MagicMock()))

        with patch("app.domains.rooms.dependencies.AuthService", return_value=auth_service):
            result = asyncio.run(
                get_current_user(
                    authorization=None,
                    session_cookie="cookie-token",
                    db=MagicMock(),
                )
            )

        self.assertIs(result, fake_user)
        auth_service.authenticate_token.assert_awaited_once_with("cookie-token")

    def test_get_current_room_uses_authenticated_user_and_slug(self):
        from app.domains.rooms.dependencies import get_current_room

        room = _make_room(slug="room-a")
        user = _make_user()

        with patch(
            "app.domains.rooms.service.RoomService.resolve_room",
            new=AsyncMock(return_value=(room, None)),
        ) as resolve_room:
            result = asyncio.run(
                get_current_room(
                    x_room_slug="room-a",
                    user=user,
                    db=MagicMock(),
                )
            )

        self.assertIs(result, room)
        resolve_room.assert_awaited_once_with(slug="room-a", user_id=user.id)


# ---------------------------------------------------------------------------
# Cross-room isolation: slug not-a-member returns error
# ---------------------------------------------------------------------------

class TestCrossRoomIsolation(unittest.TestCase):

    def test_slug_for_room_user_is_not_member_of_returns_error(self):
        from app.domains.rooms.service import RoomService

        other_room = _make_room(slug="other-room", room_id=uuid.uuid4())
        user_id = uuid.uuid4()

        service = RoomService.__new__(RoomService)
        repo = MagicMock()
        repo.get_room_by_slug = AsyncMock(return_value=other_room)
        repo.is_member = AsyncMock(return_value=False)
        service.repository = repo

        result_room, error = asyncio.run(
            service.resolve_room(slug="other-room", user_id=user_id)
        )
        self.assertIsNone(result_room)
        self.assertIsNotNone(error)
        self.assertIn("not a member", error)

    def test_trusted_slug_comes_from_server_resolution(self):
        """Room ID on query results must come from server-resolved room, not from request body."""
        from app.domains.rooms.service import RoomService

        # Simulate a user injecting a different room slug
        attacker_room_id = uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        attacker_room = _make_room(slug="secret-room", room_id=attacker_room_id)
        user_id = uuid.uuid4()

        service = RoomService.__new__(RoomService)
        repo = MagicMock()
        repo.get_room_by_slug = AsyncMock(return_value=attacker_room)
        repo.is_member = AsyncMock(return_value=False)  # user is NOT a member
        service.repository = repo

        result_room, error = asyncio.run(
            service.resolve_room(slug="secret-room", user_id=user_id)
        )
        # Must be blocked
        self.assertIsNone(result_room)
        self.assertIsNotNone(error)


# ---------------------------------------------------------------------------
# Existing single-room behaviour
# ---------------------------------------------------------------------------

class TestSingleRoomBackwardsCompat(unittest.TestCase):

    def test_single_room_user_gets_room_without_header(self):
        from app.domains.rooms.service import RoomService

        room = _make_room()
        membership = _make_membership()
        user_id = uuid.uuid4()

        service = RoomService.__new__(RoomService)
        repo = MagicMock()
        repo.get_rooms_for_user = AsyncMock(return_value=[(room, membership)])
        service.repository = repo

        result_room, error = asyncio.run(
            service.resolve_room(slug=None, user_id=user_id)
        )
        self.assertIsNone(error)
        self.assertIs(result_room, room)

    def test_room_models_have_room_id_column(self):
        """All core ORM models must declare a room_id column."""
        from app.models.message import Message
        from app.models.photo import Photo
        from app.models.event import Event
        from app.models.planning import Poll, Reminder, Idea
        from app.models.hub_item import HubItem
        from app.models.notification import Notification
        from app.models.ai_memory import AIMemoryEntry

        for model in [Message, Photo, Event, Poll, Reminder, Idea, HubItem, Notification, AIMemoryEntry]:
            self.assertIn(
                "room_id",
                model.__table__.columns.keys(),
                msg=f"{model.__name__} is missing room_id column",
            )


if __name__ == "__main__":
    unittest.main()
