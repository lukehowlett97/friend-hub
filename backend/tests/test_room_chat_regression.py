"""
Regression tests for Phase 1 multi-room chat.

Covers:
- message creation stores room_id
- WebSocket message_handler scopes message to the connection's room
- user cannot post into a room they are not a member of (no room resolved → reject)
- single-room users can send messages without manually selecting a room
- _post_bot_chat_message uses the default room
- hub bot _post_response uses the passed room_id
"""
import asyncio
import os
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

os.environ["DEBUG"] = "false"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_room(room_id=None, slug="main"):
    r = MagicMock()
    r.id = room_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    r.slug = slug
    r.status = "active"
    r.name = "Main Space"
    return r


def _make_user(session_id=None, user_id=None):
    u = MagicMock()
    u.session_id = session_id or uuid.uuid4()
    u.id = user_id or uuid.uuid4()
    u.nickname = "Alice"
    u.username = "alice"
    u.avatar_url = None
    u.avatar_emoji = None
    u.display_role = None
    u.role = "member"
    return u


def _make_message(msg_id=1, room_id=None):
    m = MagicMock()
    m.id = msg_id
    m.room_id = room_id or uuid.UUID("00000000-0000-0000-0000-000000000001")
    m.created_at = datetime.utcnow()
    m.content = "hello"
    return m


# ---------------------------------------------------------------------------
# MessageRepository.create_message passes room_id
# ---------------------------------------------------------------------------

class TestMessageRepositoryRoomId(unittest.TestCase):

    def test_create_message_stores_room_id(self):
        from app.domains.messages.repository import MessageRepository
        from app.models.message import Message

        room_id = uuid.uuid4()
        captured = []

        class FakeDB:
            def add(self, obj):
                captured.append(obj)
            async def commit(self):
                pass
            async def refresh(self, obj):
                pass

        repo = MessageRepository(FakeDB())
        asyncio.run(
            repo.create_message(
                session_id=str(uuid.uuid4()),
                content="hello",
                room_id=room_id,
            )
        )

        self.assertEqual(len(captured), 1)
        msg = captured[0]
        self.assertIsInstance(msg, Message)
        self.assertEqual(msg.room_id, room_id)

    def test_create_message_without_room_id_is_none(self):
        from app.domains.messages.repository import MessageRepository
        from app.models.message import Message

        captured = []

        class FakeDB:
            def add(self, obj):
                captured.append(obj)
            async def commit(self):
                pass
            async def refresh(self, obj):
                pass

        repo = MessageRepository(FakeDB())
        asyncio.run(
            repo.create_message(
                session_id=str(uuid.uuid4()),
                content="hello",
            )
        )
        self.assertIsNone(captured[0].room_id)


# ---------------------------------------------------------------------------
# MessageService.save_message threads room_id
# ---------------------------------------------------------------------------

class TestMessageServiceRoomId(unittest.TestCase):

    def test_save_message_passes_room_id_to_repository(self):
        from app.domains.messages.service import MessageService

        room_id = uuid.uuid4()
        user_id = uuid.uuid4()
        session_id = str(uuid.uuid4())

        service = MessageService.__new__(MessageService)
        service.message_repo = MagicMock()
        service.user_repo = MagicMock()
        service.reaction_repo = MagicMock()

        fake_msg = _make_message(room_id=room_id)
        service.message_repo.create_message = AsyncMock(return_value=fake_msg)
        service.user_repo.get_by_session_id = AsyncMock(return_value=_make_user(session_id=uuid.UUID(session_id)))

        asyncio.run(
            service.save_message(session_id, "hello", user_id=user_id, room_id=room_id)
        )

        service.message_repo.create_message.assert_awaited_once()
        kwargs = service.message_repo.create_message.call_args
        self.assertEqual(kwargs.kwargs.get("room_id") or kwargs.args[4] if len(kwargs.args) > 4 else kwargs.kwargs.get("room_id"), room_id)

    def test_get_message_context_passes_room_id_to_repository(self):
        from app.domains.messages.service import MessageService

        room_id = uuid.uuid4()
        service = MessageService.__new__(MessageService)
        service.message_repo = MagicMock()
        service.reaction_repo = MagicMock()
        service.message_repo.get_message_context_with_users = AsyncMock(return_value=[])

        asyncio.run(service.get_message_context(123, before=5, after=6, room_id=room_id))

        service.message_repo.get_message_context_with_users.assert_awaited_once_with(
            123,
            before=5,
            after=6,
            room_id=room_id,
        )


# ---------------------------------------------------------------------------
# REST message routes resolve and enforce current room
# ---------------------------------------------------------------------------

class TestMessageRoutesRoomId(unittest.TestCase):

    def test_get_messages_resolves_room_and_passes_room_id_to_chat_service(self):
        from app.api.v1.router import get_messages

        room = _make_room(room_id=uuid.uuid4(), slug="room-a")
        user = _make_user()
        captured = {}

        async def fake_get_recent_messages(self, **kwargs):
            captured.update(kwargs)
            return []

        with patch("app.api.v1.router._current_user_or_401", new=AsyncMock(return_value=user)):
            with patch(
                "app.domains.rooms.service.RoomService.resolve_room",
                new=AsyncMock(return_value=(room, None)),
            ) as resolve_room:
                with patch("app.services.chat_service.ChatService.get_recent_messages", new=fake_get_recent_messages):
                    response = asyncio.run(
                        get_messages(
                            limit=10,
                            offset=2,
                            x_room_slug="room-a",
                            authorization="Bearer token",
                            session_cookie=None,
                            db=MagicMock(),
                        )
                    )

        self.assertEqual(response.total, 0)
        resolve_room.assert_awaited_once_with(slug="room-a", user_id=user.id)
        self.assertEqual(captured["room_id"], room.id)

    def test_get_message_context_404s_for_message_outside_resolved_room(self):
        from app.api.v1.router import get_message_context
        from fastapi import HTTPException

        room = _make_room(room_id=uuid.uuid4(), slug="room-a")
        user = _make_user()
        captured = {}

        async def fake_get_message_context(self, message_id, before=25, after=25, room_id=None):
            captured["room_id"] = room_id
            return []

        with patch("app.api.v1.router._current_user_or_401", new=AsyncMock(return_value=user)):
            with patch(
                "app.domains.rooms.service.RoomService.resolve_room",
                new=AsyncMock(return_value=(room, None)),
            ):
                with patch(
                    "app.domains.messages.service.MessageService.get_message_context",
                    new=fake_get_message_context,
                ):
                    with self.assertRaises(HTTPException) as ctx:
                        asyncio.run(
                            get_message_context(
                                999,
                                before=5,
                                after=5,
                                x_room_slug="room-a",
                                authorization="Bearer token",
                                session_cookie=None,
                                db=MagicMock(),
                            )
                        )

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(captured["room_id"], room.id)


# ---------------------------------------------------------------------------
# ConnectionManager stores room per connection
# ---------------------------------------------------------------------------

class TestConnectionManagerRoom(unittest.TestCase):

    def test_get_room_returns_stored_room(self):
        from app.domains.chat.connection_manager import ConnectionManager

        manager = ConnectionManager()
        room = _make_room()
        user = _make_user()
        ws = MagicMock()
        conn_id = str(uuid.uuid4())

        manager.connect(ws, conn_id, user, room=room)
        self.assertIs(manager.get_room(conn_id), room)

    def test_get_room_returns_none_when_no_room_stored(self):
        from app.domains.chat.connection_manager import ConnectionManager

        manager = ConnectionManager()
        user = _make_user()
        ws = MagicMock()
        conn_id = str(uuid.uuid4())

        manager.connect(ws, conn_id, user)
        self.assertIsNone(manager.get_room(conn_id))

    def test_disconnect_removes_room(self):
        from app.domains.chat.connection_manager import ConnectionManager

        manager = ConnectionManager()
        room = _make_room()
        user = _make_user()
        ws = MagicMock()
        conn_id = str(uuid.uuid4())

        manager.connect(ws, conn_id, user, room=room)
        manager.disconnect(conn_id)
        self.assertIsNone(manager.get_room(conn_id))


# ---------------------------------------------------------------------------
# WebSocketMessageHandler._handle_chat_message uses connection's room_id
# ---------------------------------------------------------------------------

class TestMessageHandlerRoomId(unittest.TestCase):

    def _make_handler(self, room=None):
        from app.domains.chat.message_handler import WebSocketMessageHandler

        conn_manager = MagicMock()
        user = _make_user()
        conn_manager.get_user = MagicMock(return_value=user)
        conn_manager.get_room = MagicMock(return_value=room)
        conn_manager.broadcast = AsyncMock()
        conn_manager.broadcast_to_room = AsyncMock()
        handler = WebSocketMessageHandler(conn_manager)
        return handler, user

    def test_handle_chat_message_passes_room_id_to_save(self):
        room = _make_room()
        handler, user = self._make_handler(room=room)
        conn_id = str(uuid.uuid4())

        fake_msg = _make_message(room_id=room.id)

        with patch(
            "app.services.chat_service.ChatService.save_message",
            new=AsyncMock(return_value=(fake_msg, user.nickname, None)),
        ) as mock_save, patch(
            "app.domains.chat.message_handler._push_chat_notifications",
            new=AsyncMock(),
        ):
            asyncio.run(
                handler._handle_chat_message(
                    {"content": "hello", "reply_to_id": None},
                    conn_id,
                    MagicMock(),
                )
            )

        mock_save.assert_awaited_once()
        kwargs = mock_save.call_args.kwargs
        self.assertEqual(kwargs.get("room_id"), room.id)

    def test_handle_chat_message_no_room_passes_none(self):
        """When no room is stored on the connection, room_id=None is passed through."""
        handler, user = self._make_handler(room=None)
        conn_id = str(uuid.uuid4())
        fake_msg = _make_message(room_id=None)

        with patch(
            "app.services.chat_service.ChatService.save_message",
            new=AsyncMock(return_value=(fake_msg, user.nickname, None)),
        ) as mock_save, patch(
            "app.domains.chat.message_handler._push_chat_notifications",
            new=AsyncMock(),
        ):
            asyncio.run(
                handler._handle_chat_message(
                    {"content": "hello"},
                    conn_id,
                    MagicMock(),
                )
            )

        kwargs = mock_save.call_args.kwargs
        self.assertIsNone(kwargs.get("room_id"))


# ---------------------------------------------------------------------------
# WebSocket handshake — room resolution
# ---------------------------------------------------------------------------

class TestWebSocketRoomResolution(unittest.TestCase):

    def test_single_room_user_connects_without_room_param(self):
        """User with exactly one room can connect without ?room= query param."""
        from app.domains.rooms.service import RoomService

        room = _make_room()
        user = _make_user()

        service = RoomService.__new__(RoomService)
        repo = MagicMock()
        repo.get_rooms_for_user = AsyncMock(return_value=[(room, MagicMock())])
        service.repository = repo

        result_room, error = asyncio.run(
            service.resolve_room(slug=None, user_id=user.id)
        )
        self.assertIsNone(error)
        self.assertIs(result_room, room)

    def test_multi_room_user_without_slug_gets_error(self):
        """User with multiple rooms who sends no room slug gets an error — WS should close 4003."""
        from app.domains.rooms.service import RoomService

        room_a = _make_room(slug="a", room_id=uuid.uuid4())
        room_b = _make_room(slug="b", room_id=uuid.uuid4())
        user = _make_user()

        service = RoomService.__new__(RoomService)
        repo = MagicMock()
        repo.get_rooms_for_user = AsyncMock(return_value=[(room_a, MagicMock()), (room_b, MagicMock())])
        service.repository = repo

        result_room, error = asyncio.run(
            service.resolve_room(slug=None, user_id=user.id)
        )
        self.assertIsNone(result_room)
        self.assertIsNotNone(error)
        self.assertIn("X-Room-Slug", error)

    def test_wrong_room_slug_is_rejected(self):
        """User supplying a slug they are not a member of must be rejected."""
        from app.domains.rooms.service import RoomService

        other_room = _make_room(slug="other", room_id=uuid.uuid4())
        user = _make_user()

        service = RoomService.__new__(RoomService)
        repo = MagicMock()
        repo.get_room_by_slug = AsyncMock(return_value=other_room)
        repo.is_member = AsyncMock(return_value=False)
        service.repository = repo

        result_room, error = asyncio.run(
            service.resolve_room(slug="other", user_id=user.id)
        )
        self.assertIsNone(result_room)
        self.assertIn("not a member", error)


# ---------------------------------------------------------------------------
# _post_bot_chat_message uses default room_id
# ---------------------------------------------------------------------------

class TestPostBotChatMessageRoomId(unittest.TestCase):

    def test_uses_passed_room_id(self):
        from app.api.v1.router import _post_bot_chat_message
        from app.models.message import Message

        room_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        captured = []

        class FakeDB:
            def add(self, obj):
                captured.append(obj)
            async def flush(self):
                pass

        asyncio.run(
            _post_bot_chat_message(FakeDB(), content="beep boop", manager=None, room_id=room_id)
        )

        self.assertEqual(captured[0].room_id, room_id)

    def test_falls_back_to_default_room_id_when_not_passed(self):
        from app.api.v1.router import _post_bot_chat_message
        from app.models.room import DEFAULT_ROOM_ID

        captured = []

        class FakeDB:
            def add(self, obj):
                captured.append(obj)
            async def flush(self):
                pass

        asyncio.run(
            _post_bot_chat_message(FakeDB(), content="beep boop", manager=None)
        )

        self.assertEqual(captured[0].room_id, DEFAULT_ROOM_ID)


# ---------------------------------------------------------------------------
# Hub bot _post_response stores room_id
# ---------------------------------------------------------------------------

class TestHubBotPostResponseRoomId(unittest.TestCase):

    def _fake_db(self, captured):
        class FakeDB:
            def add(self, obj):
                captured.append(obj)
            async def commit(self):
                pass
            async def refresh(self, obj):
                # Simulate DB assigning an id so Pydantic validation succeeds
                obj.id = 1
        return FakeDB()

    def test_post_response_stores_room_id_on_message(self):
        from app.ai.bot import HubBot
        from app.models.message import Message

        bot = HubBot()
        room_id = uuid.uuid4()
        captured = []

        manager = MagicMock()
        manager.broadcast = AsyncMock()

        asyncio.run(
            bot._post_response("hello", self._fake_db(captured), manager, room_id=room_id)
        )

        self.assertEqual(len(captured), 1)
        self.assertIsInstance(captured[0], Message)
        self.assertEqual(captured[0].room_id, room_id)

    def test_post_response_none_room_id_passes_none(self):
        from app.ai.bot import HubBot
        from app.models.message import Message

        bot = HubBot()
        captured = []

        manager = MagicMock()
        manager.broadcast = AsyncMock()

        asyncio.run(bot._post_response("hello", self._fake_db(captured), manager))

        self.assertIsNone(captured[0].room_id)


if __name__ == "__main__":
    unittest.main()
