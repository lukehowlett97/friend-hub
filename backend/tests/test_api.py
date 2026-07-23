import asyncio
import os
import types
import unittest
import uuid
from pathlib import Path

os.environ["DEBUG"] = "false"

from fastapi import HTTPException

from app.api.v1 import router
from app.api.v1.router import (
    CommentCreateRequest,
    EventCreateRequest,
    _event_by_id_or_404,
    _event_creator_payload,
    _to_utc_naive,
    create_comment,
    create_event,
    get_members,
    get_messages,
)
from app.models.room import DEFAULT_ROOM_ID
from app.services.chat_service import ChatService


class TestMessageHistoryEndpoint(unittest.TestCase):
    def test_frontend_uses_v1_messages_endpoint(self):
        repo_root = Path(__file__).resolve().parents[2]
        hook_path = repo_root / "frontend" / "src" / "hooks" / "useWebSocket.jsx"
        content = hook_path.read_text(encoding="utf-8")
        self.assertIn("/api/v1/messages", content)

    def test_messages_endpoint_returns_payload(self):
        async def fake_get_recent_messages(self, limit=50, offset=0, start_at=None, end_at=None, room_id=None):
            return [
                {
                    "id": 1,
                    "session_id": "session-1",
                    "nickname": "TestUser",
                    "content": "Hello",
                    "created_at": "2025-01-01T00:00:00Z",
                    "type": "chat",
                }
            ]

        original_get_recent_messages = ChatService.get_recent_messages
        ChatService.get_recent_messages = fake_get_recent_messages
        try:
            class DummySession:
                pass

            response = asyncio.run(
                get_messages(
                    limit=1,
                    offset=0,
                    x_room_slug=None,
                    authorization=None,
                    session_cookie=None,
                    db=DummySession(),
                )
            )
            payload = response.model_dump()
            self.assertIn("messages", payload)
            self.assertEqual(payload["messages"][0]["content"], "Hello")
        finally:
            ChatService.get_recent_messages = original_get_recent_messages


class TestMembersEndpoint(unittest.TestCase):
    def test_members_endpoint_returns_roles_and_online_state(self):
        async def fake_get_members(self):
            return [
                {
                    "session_id": "session-1",
                    "nickname": "TestUser",
                    "role": "owner",
                    "is_online": True,
                    "message_count": 3,
                    "joined_at": "2025-01-01T00:00:00",
                    "last_seen": "2025-01-01T00:10:00",
                }
            ]

        from app.domains.members.service import MemberService

        original_get_members = MemberService.get_members
        MemberService.get_members = fake_get_members
        try:
            class DummySession:
                pass

            response = asyncio.run(get_members(db=DummySession(), manager=None))
            payload = response.model_dump()
            self.assertEqual(payload["members"][0]["role"], "owner")
            self.assertTrue(payload["members"][0]["is_online"])
        finally:
            MemberService.get_members = original_get_members


class TestEventEndpointHelpers(unittest.TestCase):
    def test_to_utc_naive_strips_timezone(self):
        from datetime import datetime, timezone

        value = datetime(2026, 5, 1, 12, 3, tzinfo=timezone.utc)
        result = _to_utc_naive(value)

        self.assertIsNone(result.tzinfo)
        self.assertEqual(result.isoformat(), "2026-05-01T12:03:00")

    def test_event_creator_falls_back_to_hub_item_creator(self):
        metadata = {
            "creator": {
                "id": "user-1",
                "username": "techlett",
                "nickname": "Techlett",
                "role": "member",
            }
        }

        self.assertEqual(
            _event_creator_payload(None, None, None, None, metadata),
            metadata["creator"],
        )

    def test_event_lookup_rejects_room_mismatch(self):
        from datetime import datetime
        from app.models.event import Event

        class DummyDb:
            async def get(self, model, key):
                return Event(
                    id=key,
                    group_id=1,
                    room_id=uuid.uuid4(),
                    title="Other room",
                    starts_at=datetime.utcnow(),
                )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(_event_by_id_or_404(DummyDb(), 1, 5, room_id=DEFAULT_ROOM_ID))

        self.assertEqual(ctx.exception.status_code, 404)

    def test_create_event_uses_resolved_room_id(self):
        from datetime import datetime
        from app.models.event import Event

        room_id = uuid.uuid4()
        user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Event Maker",
        )
        captured_hub_item = {}

        class DummyDb:
            def __init__(self):
                self.added = []
                self.committed = False

            def add(self, value):
                self.added.append(value)

            async def flush(self):
                for value in self.added:
                    if isinstance(value, Event) and value.id is None:
                        value.id = 44

            async def commit(self):
                self.committed = True

            async def refresh(self, value):
                pass

        class DummyBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pass

        async def fake_hub_item_for_source(db, **kwargs):
            captured_hub_item.update(kwargs)
            return types.SimpleNamespace(short_id="#E-44")

        original_current_user = router._current_user_or_401
        original_default_group = router._default_group
        original_request_room_id = router._request_room_id
        original_hub_item_for_source = router._hub_item_for_source
        original_log_activity = router._log_activity
        try:
            router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(user)
            router._default_group = lambda db: _async(types.SimpleNamespace(id=1))
            router._request_room_id = lambda db, **kwargs: _async(room_id)
            router._hub_item_for_source = fake_hub_item_for_source
            router._log_activity = lambda *args, **kwargs: _async(None)

            db = DummyDb()
            asyncio.run(create_event(
                EventCreateRequest(
                    title="Room event",
                    starts_at=datetime.utcnow(),
                    photo_tag_id="#custom",
                ),
                background_tasks=DummyBackgroundTasks(),
                db=db,
                manager=None,
            ))
        finally:
            router._current_user_or_401 = original_current_user
            router._default_group = original_default_group
            router._request_room_id = original_request_room_id
            router._hub_item_for_source = original_hub_item_for_source
            router._log_activity = original_log_activity

        event = next(value for value in db.added if isinstance(value, Event))
        self.assertEqual(event.room_id, room_id)
        self.assertEqual(captured_hub_item["room_id"], room_id)


class TestCommentEndpointHelpers(unittest.TestCase):
    def test_create_comment_checks_target_in_resolved_room(self):
        room_id = uuid.uuid4()
        user = types.SimpleNamespace(id=uuid.uuid4(), session_id=uuid.uuid4(), nickname="Commenter")
        captured_target_check = {}

        class DummyDb:
            pass

        class DummyBackgroundTasks:
            def add_task(self, *args, **kwargs):
                pass

        async def fake_target_exists(db, target_type, target_id, group_id, *, room_id=None):
            captured_target_check.update(
                {
                    "target_type": target_type,
                    "target_id": target_id,
                    "group_id": group_id,
                    "room_id": room_id,
                }
            )
            return False

        original_current_user = router._current_user_or_401
        original_default_group = router._default_group
        original_request_room_id = router._request_room_id
        original_target_exists = router._target_exists
        try:
            router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(user)
            router._default_group = lambda db: _async(types.SimpleNamespace(id=1))
            router._request_room_id = lambda db, **kwargs: _async(room_id)
            router._target_exists = fake_target_exists

            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    create_comment(
                        CommentCreateRequest(target_type="event", target_id=42, content="hello"),
                        background_tasks=DummyBackgroundTasks(),
                        db=DummyDb(),
                        manager=None,
                    )
                )
        finally:
            router._current_user_or_401 = original_current_user
            router._default_group = original_default_group
            router._request_room_id = original_request_room_id
            router._target_exists = original_target_exists

        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(captured_target_check["target_type"], "event")
        self.assertEqual(captured_target_check["target_id"], 42)
        self.assertEqual(captured_target_check["room_id"], room_id)


async def _async(value):
    return value


class TestEventCalendarExport(unittest.TestCase):
    def test_build_event_ics_includes_core_fields(self):
        from datetime import datetime

        from app.domains.events.calendar import build_event_ics
        from app.models.event import Event

        event = Event(
            id=8,
            title="Dinner, drinks; games",
            description="Bring snacks\nUse side door",
            location="Cafe; Main, London",
            starts_at=datetime(2026, 6, 1, 18, 30),
            updated_at=datetime(2026, 5, 20, 10, 0),
        )

        payload = build_event_ics(event, event_url="https://friend-hub.test/events/8")

        self.assertIn("BEGIN:VCALENDAR\r\n", payload)
        self.assertIn("UID:friend-hub-event-8@friend-hub\r\n", payload)
        self.assertIn("DTSTART:20260601T183000Z\r\n", payload)
        self.assertIn("DTEND:20260601T203000Z\r\n", payload)
        self.assertIn("SUMMARY:Dinner\\, drinks\\; games\r\n", payload)
        self.assertIn("DESCRIPTION:Bring snacks\\nUse side door\r\n", payload)
        self.assertIn("LOCATION:Cafe\\; Main\\, London\r\n", payload)
        self.assertIn("URL:https://friend-hub.test/events/8\r\n", payload)
        self.assertIn("STATUS:CONFIRMED\r\n", payload)
        self.assertIn("LAST-MODIFIED:20260520T100000Z\r\n", payload)
