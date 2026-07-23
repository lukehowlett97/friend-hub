"""Phase 2 (Chat Council) — agenda / chat-event tests."""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import router
from app.api.v1.router import (
    ChatEventCreateRequest,
    create_chat_event,
    get_poll_card,
    list_live_agenda_motions,
    vote_poll,
    PollVoteRequest,
    _agenda_motion_marker,
    _apply_closed_agenda_result_if_needed,
    _derive_poll_status,
    _event_type_label,
    _format_chat_event_announcement,
    _iso_utc,
    _validate_chat_event,
)
from app.models.message import Message, User, UserRole
from app.models.planning import (
    POLL_SOURCE_CHAT_AGENDA,
    Poll,
    PollEventType,
    PollOption,
    PollStatus,
    PollVoteMode,
)


class DummyDb:
    """Async-compatible in-memory DB stub for chat-event endpoint tests."""

    def __init__(self, target_user=None, poll=None, options=None):
        self.added = []
        self.committed = False
        self._target_user = target_user
        self._poll = poll
        self._options = options or []

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        for item in self.added:
            if isinstance(item, Poll) and getattr(item, "id", None) is None:
                item.id = 7
            if isinstance(item, Message) and getattr(item, "id", None) is None:
                item.id = 91
            if isinstance(item, PollOption) and getattr(item, "id", None) is None:
                item.id = len(self.added)

    async def commit(self):
        self.committed = True

    async def refresh(self, value):
        return None

    async def get(self, model, key):
        if model is Poll:
            return self._poll
        return None

    async def execute(self, stmt):
        # Endpoint queries: User row lookup for target.
        target = self._target_user

        class Result:
            def scalar_one_or_none(self_inner):
                return target

            def fetchall(self_inner):
                return [(opt.id,) for opt in (self._options if False else [])]

        return Result()


def _async(value):
    async def _coro():
        return value
    return _coro()


class TestPollEnumValues(unittest.TestCase):
    def test_event_types(self):
        self.assertEqual(
            {e.value for e in PollEventType},
            {"nickname_vote", "role_vote", "general_vote"},
        )

    def test_status_values(self):
        self.assertEqual(
            {s.value for s in PollStatus},
            {"scheduled", "live", "closed", "cancelled"},
        )


class TestPollModelColumns(unittest.TestCase):
    def test_chat_event_columns_present(self):
        cols = {c.key for c in Poll.__table__.columns}
        for name in (
            "event_type",
            "target_user_id",
            "proposed_nickname",
            "proposed_role",
            "voting_opens_at",
            "source",
            "status",
            "open_message_id",
            "result_message_id",
        ):
            self.assertIn(name, cols, f"missing column: {name}")


class TestMigration(unittest.TestCase):
    def test_migration_020_exists(self):
        repo_root = Path(__file__).resolve().parents[2]
        migration = repo_root / "backend" / "migrations" / "020_add_chat_event_polls.sql"
        self.assertTrue(migration.exists(), "Migration 020 not found")
        body = migration.read_text(encoding="utf-8")
        for fragment in (
            "event_type",
            "target_user_id",
            "proposed_nickname",
            "proposed_role",
            "voting_opens_at",
            "source",
            "status",
        ):
            self.assertIn(fragment, body)


class TestDerivePollStatus(unittest.TestCase):
    def test_scheduled_when_opens_in_future(self):
        poll = Poll()
        now = datetime.utcnow()
        poll.voting_opens_at = now + timedelta(minutes=10)
        poll.deadline_at = now + timedelta(minutes=30)
        self.assertEqual(_derive_poll_status(poll), "scheduled")

    def test_live_when_in_voting_window(self):
        poll = Poll()
        now = datetime.utcnow()
        poll.voting_opens_at = now - timedelta(minutes=2)
        poll.deadline_at = now + timedelta(minutes=10)
        self.assertEqual(_derive_poll_status(poll), "live")

    def test_closed_when_past_deadline(self):
        poll = Poll()
        now = datetime.utcnow()
        poll.voting_opens_at = now - timedelta(minutes=20)
        poll.deadline_at = now - timedelta(minutes=1)
        self.assertEqual(_derive_poll_status(poll), "closed")

    def test_cancelled_status_preserved(self):
        poll = Poll()
        poll.status = "cancelled"
        poll.voting_opens_at = datetime.utcnow() - timedelta(minutes=5)
        poll.deadline_at = datetime.utcnow() + timedelta(minutes=5)
        self.assertEqual(_derive_poll_status(poll), "cancelled")

    def test_legacy_poll_without_opens_at_is_live(self):
        poll = Poll()
        poll.deadline_at = datetime.utcnow() + timedelta(minutes=10)
        self.assertEqual(_derive_poll_status(poll), "live")


class TestValidateChatEvent(unittest.TestCase):
    def _admin(self):
        return types.SimpleNamespace(id=uuid.uuid4(), nickname="Admin",
                                     role=types.SimpleNamespace(value="admin"))

    def _member(self):
        return types.SimpleNamespace(id=uuid.uuid4(), nickname="Mike",
                                     role=types.SimpleNamespace(value="member"))

    def test_invalid_event_type_rejected(self):
        request = ChatEventCreateRequest(
            event_type="laser_vote", title="t",
            voting_opens_at=datetime.utcnow(),
            voting_closes_at=datetime.utcnow() + timedelta(minutes=5),
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("event_type", str(ctx.exception.detail))

    def test_close_before_open_rejected(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="general_vote", title="t",
            voting_opens_at=now + timedelta(minutes=10),
            voting_closes_at=now + timedelta(minutes=5),
            poll_question="q?", poll_options=["a", "b"],
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("voting_closes_at", str(ctx.exception.detail))

    def test_nickname_vote_requires_target_member(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="nickname_vote", title="Rename Mike",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            proposed_nickname="The Maybe Merchant",
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("target_user_id", str(ctx.exception.detail))

    def test_role_vote_requires_target_member(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="role_vote", title="Crown Luke",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            proposed_role="Vibes Officer",
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("target_user_id", str(ctx.exception.detail))

    def test_nickname_vote_requires_proposed_nickname(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="nickname_vote", title="Rename Mike",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            target_user_id=str(uuid.uuid4()),
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("proposed_nickname", str(ctx.exception.detail))

    def test_role_vote_requires_proposed_role(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="role_vote", title="Crown Luke",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            target_user_id=str(uuid.uuid4()),
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("proposed_role", str(ctx.exception.detail))

    def test_general_vote_requires_options(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="general_vote", title="Friday plans",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            poll_question="Where Friday?", poll_options=["pub"],
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._admin())
        self.assertIn("two options", str(ctx.exception.detail))

    def test_nickname_vote_blocked_for_member(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="nickname_vote", title="Rename Mike",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            target_user_id=str(uuid.uuid4()),
            proposed_nickname="The Maybe Merchant",
        )
        with self.assertRaises(Exception) as ctx:
            _validate_chat_event(request, self._member())
        self.assertEqual(ctx.exception.status_code, 403)

    def test_general_vote_allowed_for_member(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="general_vote", title="Friday plans",
            voting_opens_at=now,
            voting_closes_at=now + timedelta(minutes=10),
            poll_question="Where Friday?",
            poll_options=["Pub", "House"],
        )
        result = _validate_chat_event(request, self._member())
        self.assertEqual(result[0], "general_vote")


class TestFormatChatEventAnnouncement(unittest.TestCase):
    def test_general_vote_includes_options(self):
        now = datetime.utcnow()
        poll = Poll(
            question="Where Friday?",
            event_type="general_vote",
            voting_opens_at=now,
            deadline_at=now + timedelta(minutes=10),
        )
        text = _format_chat_event_announcement(poll, None, ["Pub", "House"])
        self.assertIn("Where Friday?", text)
        self.assertIn("Pub", text)
        self.assertIn("House", text)
        self.assertIn("Council motion", text)

    def test_nickname_vote_uses_target_nickname(self):
        now = datetime.utcnow()
        target = types.SimpleNamespace(nickname="Mike")
        poll = Poll(
            question="?",
            event_type="nickname_vote",
            proposed_nickname="The Maybe Merchant",
            voting_opens_at=now,
            deadline_at=now + timedelta(minutes=10),
        )
        text = _format_chat_event_announcement(poll, target, ["Yes", "No"])
        self.assertIn("Mike", text)
        self.assertIn("The Maybe Merchant", text)


class TestCreateChatEventEndpoint(unittest.TestCase):
    def setUp(self):
        self.original_current_user = router._current_user_or_401
        self.original_default_group = router._default_group
        self.original_request_room_id = router._request_room_id
        self.original_hub_item = router._hub_item_for_source
        self.original_log_activity = router._log_activity
        self.original_broadcast = router._broadcast_bot_message
        self.hub_item_calls = []
        self.broadcast_calls = []
        self.room_id = uuid.uuid4()

        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Admin",
            username="admin",
            role=types.SimpleNamespace(value="admin"),
        )
        self.group = types.SimpleNamespace(id=1)
        router._current_user_or_401 = lambda *args, **kwargs: _async(self.user)
        router._default_group = lambda db: _async(self.group)
        router._request_room_id = lambda *args, **kwargs: _async(self.room_id)

        async def _no_op_hub_item(*a, **k):
            self.hub_item_calls.append({"args": a, "kwargs": k})
            return None
        async def _no_op_log(*a, **k): return None
        async def _no_op_broadcast(*a, **k):
            self.broadcast_calls.append({"args": a, "kwargs": k})
            return None

        router._hub_item_for_source = _no_op_hub_item
        router._log_activity = _no_op_log
        router._broadcast_bot_message = _no_op_broadcast

    def tearDown(self):
        router._current_user_or_401 = self.original_current_user
        router._default_group = self.original_default_group
        router._request_room_id = self.original_request_room_id
        router._hub_item_for_source = self.original_hub_item
        router._log_activity = self.original_log_activity
        router._broadcast_bot_message = self.original_broadcast

    def _bg(self):
        bg = types.SimpleNamespace()
        bg.tasks = []
        bg.add_task = lambda fn, *a, **kw: bg.tasks.append((fn, a, kw))
        return bg

    def test_general_vote_creates_poll_and_chat_message(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="general_vote",
            title="Friday plans",
            voting_opens_at=now + timedelta(minutes=1),
            voting_closes_at=now + timedelta(minutes=11),
            poll_question="Where Friday?",
            poll_options=["Pub", "House", "Town"],
        )
        db = DummyDb()
        bg = self._bg()
        result = asyncio.run(create_chat_event(
            request=request,
            background_tasks=bg,
            authorization="Bearer x",
            db=db,
            manager=None,
        ))
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["poll_status"], "scheduled")

        polls = [a for a in db.added if isinstance(a, Poll)]
        self.assertEqual(len(polls), 1)
        poll = polls[0]
        self.assertEqual(poll.event_type, "general_vote")
        self.assertEqual(poll.source, POLL_SOURCE_CHAT_AGENDA)
        self.assertIsNotNone(poll.voting_opens_at)
        self.assertIsNotNone(poll.deadline_at)

        options = [a for a in db.added if isinstance(a, PollOption)]
        self.assertEqual([o.label for o in options], ["Pub", "House", "Town"])

        messages = [a for a in db.added if isinstance(a, Message)]
        self.assertEqual(len(messages), 1)
        self.assertIn("Where Friday?", messages[0].content)
        self.assertEqual(poll.open_message_id, messages[0].id)
        self.assertEqual(poll.room_id, self.room_id)
        self.assertEqual(messages[0].room_id, self.room_id)
        self.assertEqual(self.hub_item_calls[0]["kwargs"]["room_id"], self.room_id)
        self.assertEqual(self.broadcast_calls[0]["kwargs"]["room_id"], self.room_id)

    def test_nickname_vote_uses_yes_no_options(self):
        now = datetime.utcnow()
        target = types.SimpleNamespace(
            id=uuid.uuid4(),
            nickname="Mike",
        )
        request = ChatEventCreateRequest(
            event_type="nickname_vote",
            title="Rename Mike",
            voting_opens_at=now + timedelta(minutes=1),
            voting_closes_at=now + timedelta(minutes=11),
            target_user_id=str(target.id),
            proposed_nickname="The Maybe Merchant",
        )
        db = DummyDb(target_user=target)
        bg = self._bg()
        result = asyncio.run(create_chat_event(
            request=request,
            background_tasks=bg,
            authorization="Bearer x",
            db=db,
            manager=None,
        ))
        self.assertEqual(result["status"], "created")

        poll = next(a for a in db.added if isinstance(a, Poll))
        self.assertEqual(poll.event_type, "nickname_vote")
        self.assertEqual(poll.proposed_nickname, "The Maybe Merchant")
        self.assertEqual(poll.target_user_id, target.id)
        self.assertIn("Mike", poll.question)

        options = [a.label for a in db.added if isinstance(a, PollOption)]
        self.assertEqual(options, ["Yes", "No"])

    def test_role_vote_requires_admin(self):
        member_user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Member",
            role=types.SimpleNamespace(value="member"),
        )
        router._current_user_or_401 = lambda *args, **kwargs: _async(member_user)
        target = types.SimpleNamespace(id=uuid.uuid4(), nickname="Luke")
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="role_vote",
            title="Crown Luke",
            voting_opens_at=now + timedelta(minutes=1),
            voting_closes_at=now + timedelta(minutes=11),
            target_user_id=str(target.id),
            proposed_role="Vibes Officer",
        )
        with self.assertRaises(Exception) as ctx:
            asyncio.run(create_chat_event(
                request=request,
                background_tasks=self._bg(),
                authorization="Bearer x",
                db=DummyDb(target_user=target),
                manager=None,
            ))
        self.assertEqual(ctx.exception.status_code, 403)


class TestVotingWhileScheduled(unittest.TestCase):
    def setUp(self):
        self.original_current_user = router._current_user_or_401
        self.original_default_group = router._default_group
        self.original_request_room_id = router._request_room_id
        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="V",
            role=types.SimpleNamespace(value="member"),
        )
        self.group = types.SimpleNamespace(id=1)
        router._current_user_or_401 = lambda *args, **kwargs: _async(self.user)
        router._default_group = lambda db: _async(self.group)
        router._request_room_id = lambda *args, **kwargs: _async(None)

    def tearDown(self):
        router._current_user_or_401 = self.original_current_user
        router._default_group = self.original_default_group
        router._request_room_id = self.original_request_room_id

    def test_vote_rejected_when_scheduled(self):
        now = datetime.utcnow()
        poll = Poll(
            id=4,
            group_id=1,
            question="q?",
            voting_opens_at=now + timedelta(minutes=10),
            deadline_at=now + timedelta(minutes=20),
        )
        db = DummyDb(poll=poll)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(vote_poll(
                poll_id=4,
                request=PollVoteRequest(option_ids=[1]),
                authorization="Bearer x",
                db=db,
            ))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not opened", str(ctx.exception.detail))


# ── Phase 3 (Chat-rendered agenda cards) ─────────────────────────────────────

class TestEventTypeLabel(unittest.TestCase):
    def test_known_event_types(self):
        self.assertEqual(_event_type_label("nickname_vote"), "Nickname motion")
        self.assertEqual(_event_type_label("role_vote"), "Role motion")
        self.assertEqual(_event_type_label("general_vote"), "Council motion")

    def test_unknown_returns_none(self):
        self.assertIsNone(_event_type_label(None))
        self.assertIsNone(_event_type_label(""))
        self.assertIsNone(_event_type_label("laser_vote"))


class TestAgendaMarker(unittest.TestCase):
    def test_marker_format(self):
        self.assertEqual(_agenda_motion_marker(7), "[[agenda-poll:7]]")
        self.assertEqual(_agenda_motion_marker(123), "[[agenda-poll:123]]")


class _AgendaResultDb:
    def __init__(self, target_user=None):
        self.target_user = target_user
        self.committed = False

    async def get(self, model, key):
        if model is User:
            return self.target_user
        return None

    async def commit(self):
        self.committed = True


class TestClosedAgendaResultApplication(unittest.TestCase):
    def test_yes_winning_nickname_motion_updates_target(self):
        target_id = uuid.uuid4()
        target = types.SimpleNamespace(id=target_id, nickname="Conor", display_role=None, updated_at=None)
        poll = Poll(
            id=10,
            target_user_id=target_id,
            source=POLL_SOURCE_CHAT_AGENDA,
            event_type=PollEventType.nickname_vote.value,
            proposed_nickname="Binman Name",
            status=PollStatus.live.value,
        )
        options = [
            {"id": 1, "label": "Yes", "vote_count": 1},
            {"id": 2, "label": "No", "vote_count": 0},
        ]

        db = _AgendaResultDb(target)
        changed = asyncio.run(_apply_closed_agenda_result_if_needed(
            db,
            poll,
            options,
            PollStatus.closed.value,
        ))

        self.assertTrue(changed)
        self.assertTrue(db.committed)
        self.assertEqual(target.nickname, "Binman Name")
        self.assertEqual(poll.status, PollStatus.closed.value)
        self.assertIsNotNone(target.updated_at)

    def test_yes_winning_role_motion_updates_target(self):
        target_id = uuid.uuid4()
        target = types.SimpleNamespace(id=target_id, nickname="Conor", display_role="Citizen", updated_at=None)
        poll = Poll(
            id=11,
            target_user_id=target_id,
            source=POLL_SOURCE_CHAT_AGENDA,
            event_type=PollEventType.role_vote.value,
            proposed_role="Binman 2",
            status=PollStatus.live.value,
        )
        options = [
            {"id": 1, "label": "Yes", "vote_count": 1},
            {"id": 2, "label": "No", "vote_count": 0},
        ]

        changed = asyncio.run(_apply_closed_agenda_result_if_needed(
            _AgendaResultDb(target),
            poll,
            options,
            PollStatus.closed.value,
        ))

        self.assertTrue(changed)
        self.assertEqual(target.display_role, "Binman 2")
        self.assertEqual(poll.status, PollStatus.closed.value)

    def test_no_winning_motion_does_not_update_target(self):
        target_id = uuid.uuid4()
        target = types.SimpleNamespace(id=target_id, nickname="Conor", display_role="Citizen", updated_at=None)
        poll = Poll(
            id=12,
            target_user_id=target_id,
            source=POLL_SOURCE_CHAT_AGENDA,
            event_type=PollEventType.nickname_vote.value,
            proposed_nickname="Binman Name",
            status=PollStatus.closed.value,
        )
        options = [
            {"id": 1, "label": "Yes", "vote_count": 0},
            {"id": 2, "label": "No", "vote_count": 1},
        ]

        changed = asyncio.run(_apply_closed_agenda_result_if_needed(
            _AgendaResultDb(target),
            poll,
            options,
            PollStatus.closed.value,
        ))

        self.assertFalse(changed)
        self.assertEqual(target.nickname, "Conor")
        self.assertIsNone(target.updated_at)


class TestIsoUtc(unittest.TestCase):
    """Datetimes emitted to the API must carry an explicit Z so JS doesn't
    parse them as local time (which was producing BST/UTC drift in the
    agenda card)."""

    def test_naive_datetime_gets_z_suffix(self):
        dt = datetime(2026, 5, 11, 21, 53, 0)
        result = _iso_utc(dt)
        self.assertTrue(result.endswith("Z"), f"expected Z suffix, got {result!r}")
        self.assertEqual(result, "2026-05-11T21:53:00Z")

    def test_none_passes_through(self):
        self.assertIsNone(_iso_utc(None))

    def test_announcement_does_not_embed_raw_utc_times(self):
        """The bot prose used to say 'Voting opens HH:MM and closes HH:MM' in
        UTC, but the card below shows localised times. Avoid duplication so
        viewers don't see two different times."""
        now = datetime(2026, 5, 11, 21, 42)
        poll = Poll(
            question="Where Friday?",
            event_type="general_vote",
            voting_opens_at=now,
            deadline_at=now + timedelta(minutes=11),
        )
        text = _format_chat_event_announcement(poll, None, ["Pub", "House"])
        self.assertNotIn("21:42", text)
        self.assertNotIn("21:53", text)
        self.assertNotIn("Voting opens", text)
        # But the question + options are still there for fallback context
        self.assertIn("Where Friday?", text)
        self.assertIn("Pub", text)


class TestCreateChatEventEmbedsAgendaMarker(unittest.TestCase):
    """The bot announcement posted by /chat-events must include the marker
    so the frontend can swap the plain text for an AgendaPollCard."""

    def setUp(self):
        self.original_current_user = router._current_user_or_401
        self.original_default_group = router._default_group
        self.original_request_room_id = router._request_room_id
        self.original_hub_item = router._hub_item_for_source
        self.original_log_activity = router._log_activity
        self.original_broadcast = router._broadcast_bot_message

        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="Admin",
            username="admin",
            role=types.SimpleNamespace(value="admin"),
        )
        self.group = types.SimpleNamespace(id=1)
        router._current_user_or_401 = lambda *args, **kwargs: _async(self.user)
        router._default_group = lambda db: _async(self.group)
        router._request_room_id = lambda *args, **kwargs: _async(None)

        async def _no_op(*a, **k): return None
        router._hub_item_for_source = _no_op
        router._log_activity = _no_op
        router._broadcast_bot_message = _no_op

    def tearDown(self):
        router._current_user_or_401 = self.original_current_user
        router._default_group = self.original_default_group
        router._request_room_id = self.original_request_room_id
        router._hub_item_for_source = self.original_hub_item
        router._log_activity = self.original_log_activity
        router._broadcast_bot_message = self.original_broadcast

    def _bg(self):
        bg = types.SimpleNamespace()
        bg.tasks = []
        bg.add_task = lambda fn, *a, **kw: bg.tasks.append((fn, a, kw))
        return bg

    def test_announcement_contains_agenda_marker(self):
        now = datetime.utcnow()
        request = ChatEventCreateRequest(
            event_type="general_vote",
            title="Friday plans",
            voting_opens_at=now + timedelta(minutes=1),
            voting_closes_at=now + timedelta(minutes=11),
            poll_question="Where Friday?",
            poll_options=["Pub", "House"],
        )
        db = DummyDb()
        result = asyncio.run(create_chat_event(
            request=request,
            background_tasks=self._bg(),
            authorization="Bearer x",
            db=db,
            manager=None,
        ))
        self.assertEqual(result["status"], "created")
        messages = [a for a in db.added if isinstance(a, Message)]
        self.assertEqual(len(messages), 1)
        poll = next(a for a in db.added if isinstance(a, Poll))
        self.assertIn(_agenda_motion_marker(poll.id), messages[0].content)


# ── Endpoint helpers for poll-card / live-agenda / vote-returns-card ─────────


class _CardOnlyDb:
    """Minimal db stub for endpoints that only call db.get(Poll) before
    delegating to a patched _build_poll_card."""

    def __init__(self, poll=None):
        self._poll = poll

    async def get(self, model, key):
        if model is Poll:
            return self._poll
        return None


class _LiveAgendaDb:
    """Stub that returns a sequence of Poll rows from scalars().all()."""

    def __init__(self, polls):
        self._polls = polls

    async def execute(self, _stmt):
        polls = self._polls

        class _Scalars:
            def all(self_inner):
                return polls

        class _Result:
            def scalars(self_inner):
                return _Scalars()

        return _Result()


class TestGetPollCardEndpoint(unittest.TestCase):
    def setUp(self):
        self.original_default_group = router._default_group
        self.original_optional_user = router._current_user_optional
        self.original_request_room_id = router._request_room_id
        self.original_build_card = router._build_poll_card
        self.group = types.SimpleNamespace(id=1)
        router._default_group = lambda db: _async(self.group)
        router._current_user_optional = lambda authorization, db: _async(None)
        router._request_room_id = lambda *args, **kwargs: _async(None)

    def tearDown(self):
        router._default_group = self.original_default_group
        router._current_user_optional = self.original_optional_user
        router._request_room_id = self.original_request_room_id
        router._build_poll_card = self.original_build_card

    def test_returns_card_payload(self):
        poll = Poll(id=8, group_id=1, question="?", deadline_at=datetime.utcnow() + timedelta(minutes=5))

        async def _fake_card(db, poll_arg, user_id):
            return {"id": poll_arg.id, "status": "live", "options": []}

        router._build_poll_card = _fake_card

        result = asyncio.run(get_poll_card(
            poll_id=8,
            authorization=None,
            db=_CardOnlyDb(poll=poll),
        ))
        self.assertIn("card", result)
        self.assertEqual(result["card"]["id"], 8)
        self.assertEqual(result["card"]["status"], "live")

    def test_404_when_missing(self):
        with self.assertRaises(Exception) as ctx:
            asyncio.run(get_poll_card(
                poll_id=99,
                authorization=None,
                db=_CardOnlyDb(poll=None),
            ))
        self.assertEqual(ctx.exception.status_code, 404)


class TestLiveAgendaEndpoint(unittest.TestCase):
    def setUp(self):
        self.original_default_group = router._default_group
        self.original_optional_user = router._current_user_optional
        self.original_request_room_id = router._request_room_id
        self.original_build_card = router._build_poll_card
        self.group = types.SimpleNamespace(id=1)
        router._default_group = lambda db: _async(self.group)
        router._current_user_optional = lambda authorization, db: _async(None)
        router._request_room_id = lambda *args, **kwargs: _async(None)

        async def _fake_card(db, poll, user_id):
            return {
                "id": poll.id,
                "title": poll.question,
                "status": _derive_poll_status(poll),
            }

        router._build_poll_card = _fake_card

    def tearDown(self):
        router._default_group = self.original_default_group
        router._current_user_optional = self.original_optional_user
        router._request_room_id = self.original_request_room_id
        router._build_poll_card = self.original_build_card

    def test_only_live_chat_agenda_polls_returned(self):
        now = datetime.utcnow()
        live = Poll(
            id=1, group_id=1, question="Live now",
            voting_opens_at=now - timedelta(minutes=1),
            deadline_at=now + timedelta(minutes=10),
            source=POLL_SOURCE_CHAT_AGENDA,
        )
        scheduled = Poll(
            id=2, group_id=1, question="Coming up",
            voting_opens_at=now + timedelta(minutes=10),
            deadline_at=now + timedelta(minutes=30),
            source=POLL_SOURCE_CHAT_AGENDA,
        )
        closed = Poll(
            id=3, group_id=1, question="Done",
            voting_opens_at=now - timedelta(minutes=30),
            deadline_at=now - timedelta(minutes=1),
            source=POLL_SOURCE_CHAT_AGENDA,
        )
        db = _LiveAgendaDb([live, scheduled, closed])
        result = asyncio.run(list_live_agenda_motions(
            authorization=None,
            db=db,
        ))
        ids = [m["id"] for m in result["motions"]]
        self.assertEqual(ids, [1])
        self.assertEqual(result["total"], 1)


class TestVotePollReturnsCard(unittest.TestCase):
    def setUp(self):
        self.original_current_user = router._current_user_or_401
        self.original_default_group = router._default_group
        self.original_request_room_id = router._request_room_id
        self.original_log_activity = router._log_activity
        self.original_build_card = router._build_poll_card

        self.user = types.SimpleNamespace(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            nickname="V",
            role=types.SimpleNamespace(value="member"),
        )
        self.group = types.SimpleNamespace(id=1)
        router._current_user_or_401 = lambda *args, **kwargs: _async(self.user)
        router._default_group = lambda db: _async(self.group)
        router._request_room_id = lambda *args, **kwargs: _async(None)

        async def _no_op_log(*a, **k): return None
        router._log_activity = _no_op_log

        async def _fake_card(db, poll, user_id):
            return {"id": poll.id, "status": "live", "current_user_vote": [11]}

        router._build_poll_card = _fake_card

    def tearDown(self):
        router._current_user_or_401 = self.original_current_user
        router._default_group = self.original_default_group
        router._request_room_id = self.original_request_room_id
        router._log_activity = self.original_log_activity
        router._build_poll_card = self.original_build_card

    def test_returns_card_on_success(self):
        now = datetime.utcnow()
        poll = Poll(
            id=5, group_id=1, question="q?",
            voting_opens_at=now - timedelta(minutes=1),
            deadline_at=now + timedelta(minutes=10),
            vote_mode=PollVoteMode.single,
        )

        class _VoteDb:
            def __init__(self_inner, poll):
                self_inner._poll = poll
                self_inner.added = []
                self_inner.committed = False

            async def get(self_inner, model, key):
                if model is Poll:
                    return self_inner._poll
                return None

            async def execute(self_inner, _stmt):
                # All queries the endpoint runs (option-id validation, delete prior
                # votes, etc.) — return a result that yields option id 11 as valid.
                class Result:
                    def fetchall(self_innermost):
                        return [(11,)]

                return Result()

            def add(self_inner, value):
                self_inner.added.append(value)

            async def commit(self_inner):
                self_inner.committed = True

        db = _VoteDb(poll)
        result = asyncio.run(vote_poll(
            poll_id=5,
            request=PollVoteRequest(option_ids=[11]),
            authorization="Bearer x",
            db=db,
        ))
        self.assertEqual(result["status"], "voted")
        self.assertIn("card", result)
        self.assertEqual(result["card"]["current_user_vote"], [11])


if __name__ == "__main__":
    unittest.main()
