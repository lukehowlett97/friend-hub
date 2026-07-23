"""Tests for creator/admin edit permissions, history recording, and tag editing
on the PATCH /polls, /ideas, /reminders endpoints."""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta

os.environ["DEBUG"] = "false"
os.environ.setdefault("DATABASE_PASSWORD", "changeme")

from app.api.v1 import router
from app.api.v1.router import (
    IdeaUpdateRequest,
    PollUpdateRequest,
    ReminderUpdateRequest,
    update_idea,
    update_poll,
    update_reminder,
)
from app.models.planning import (
    POLL_SOURCE_CHAT_AGENDA,
    Idea,
    IdeaStatus,
    ItemHistory,
    Poll,
    Reminder,
)
from app.models.room import DEFAULT_ROOM_ID


def _async(value):
    async def _coro():
        return value
    return _coro()


class _EditDb:
    """Minimal stub. Returns a single tracked object from db.get() and supports
    add()/flush()/commit() so history rows can be inspected by tests."""

    def __init__(self, *, idea=None, poll=None, reminder=None):
        self._idea = idea
        self._poll = poll
        self._reminder = reminder
        self.added: list = []
        self.committed = False

    async def get(self, model, key):
        if model is Idea:
            return self._idea
        if model is Poll:
            return self._poll
        if model is Reminder:
            return self._reminder
        return None

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True

    async def refresh(self, _value):
        return None

    async def execute(self, _stmt):
        # Reminder update queries the assignee. Return a result that yields none.
        class _Result:
            def scalar_one_or_none(self_inner): return None
            def fetchall(self_inner): return []
        return _Result()


def _admin(user_id=None):
    return types.SimpleNamespace(
        id=user_id or uuid.uuid4(),
        session_id=uuid.uuid4(),
        nickname="Admin",
        role=types.SimpleNamespace(value="admin"),
    )


def _member(user_id=None):
    return types.SimpleNamespace(
        id=user_id or uuid.uuid4(),
        session_id=uuid.uuid4(),
        nickname="Member",
        role=types.SimpleNamespace(value="member"),
    )


class _EditBaseTest(unittest.TestCase):
    """Common harness: patches helpers and tracks calls."""

    def setUp(self):
        self.original_current_user = router._current_user_or_401
        self.original_default_group = router._default_group
        self.original_load_hub = router._load_hub_item_for_source
        self.original_hub_item = router._hub_item_for_source
        self.original_log_activity = router._log_activity
        self.original_replace_assignees = getattr(router, "_replace_reminder_assignees", None)
        self.original_request_room_id = router._request_room_id

        self.group = types.SimpleNamespace(id=1)
        router._default_group = lambda db: _async(self.group)

        self._hub_item_calls: list[dict] = []

        async def _no_op_log(*a, **k): return None
        router._log_activity = _no_op_log
        router._request_room_id = lambda db, **kwargs: _async(DEFAULT_ROOM_ID)

        async def _load_hub_item(db, item_type, source_id):
            return None  # Tests that need a hub_item override this.

        async def _hub_item_for_source(db, **kwargs):
            self._hub_item_calls.append(kwargs)
            return types.SimpleNamespace(**kwargs)

        router._load_hub_item_for_source = _load_hub_item
        router._hub_item_for_source = _hub_item_for_source

        if self.original_replace_assignees is not None:
            async def _no_op_assignees(*a, **k): return None
            router._replace_reminder_assignees = _no_op_assignees

    def tearDown(self):
        router._current_user_or_401 = self.original_current_user
        router._default_group = self.original_default_group
        router._load_hub_item_for_source = self.original_load_hub
        router._hub_item_for_source = self.original_hub_item
        router._log_activity = self.original_log_activity
        router._request_room_id = self.original_request_room_id
        if self.original_replace_assignees is not None:
            router._replace_reminder_assignees = self.original_replace_assignees


# ── /polls/{id} ──────────────────────────────────────────────────────────────


class TestUpdatePollPermissions(_EditBaseTest):
    def test_non_creator_non_admin_rejected(self):
        creator_id = uuid.uuid4()
        other = _member()
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(other)
        poll = Poll(
            room_id=DEFAULT_ROOM_ID,
            id=1, group_id=1, question="q?",
            created_by_user_id=creator_id,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )
        db = _EditDb(poll=poll)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(update_poll(
                poll_id=1,
                request=PollUpdateRequest(title="New title"),
                authorization="Bearer x",
                db=db,
            ))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_creator_can_edit(self):
        creator_id = uuid.uuid4()
        creator = _member(user_id=creator_id)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(creator)
        poll = Poll(
            room_id=DEFAULT_ROOM_ID,
            id=2, group_id=1, question="q?",
            created_by_user_id=creator_id,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )
        db = _EditDb(poll=poll)
        result = asyncio.run(update_poll(
            poll_id=2,
            request=PollUpdateRequest(title="Renamed"),
            authorization="Bearer x",
            db=db,
        ))
        self.assertEqual(result["status"], "updated")
        # hub_item_for_source was called with new title
        self.assertTrue(any(c.get("title") == "Renamed" for c in self._hub_item_calls))

    def test_admin_can_edit_other_users_poll(self):
        creator_id = uuid.uuid4()
        admin = _admin()  # different id
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(admin)
        poll = Poll(
            room_id=DEFAULT_ROOM_ID,
            id=3, group_id=1, question="q?",
            created_by_user_id=creator_id,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )
        db = _EditDb(poll=poll)
        result = asyncio.run(update_poll(
            poll_id=3,
            request=PollUpdateRequest(description="Added context"),
            authorization="Bearer x",
            db=db,
        ))
        self.assertEqual(result["status"], "updated")


class TestUpdatePollHistory(_EditBaseTest):
    def test_history_records_title_desc_tag_changes(self):
        creator_id = uuid.uuid4()
        creator = _member(user_id=creator_id)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(creator)

        # Pretend an existing hub_item already had a title/body/tags
        async def _load_hub_item(db, item_type, source_id):
            return types.SimpleNamespace(
                title="Old title",
                body="Old body",
                tags=["agenda", "general_vote"],
            )
        router._load_hub_item_for_source = _load_hub_item

        poll = Poll(
            room_id=DEFAULT_ROOM_ID,
            id=4, group_id=1, question="q?",
            created_by_user_id=creator_id,
            source=POLL_SOURCE_CHAT_AGENDA,
            deadline_at=datetime.utcnow() + timedelta(hours=1),
        )
        db = _EditDb(poll=poll)
        asyncio.run(update_poll(
            poll_id=4,
            request=PollUpdateRequest(
                title="New title",
                description="New body",
                tags=["agenda", "council"],
            ),
            authorization="Bearer x",
            db=db,
        ))
        history_rows = [a for a in db.added if isinstance(a, ItemHistory)]
        self.assertEqual(len(history_rows), 1)
        changes = history_rows[0].changes
        self.assertEqual(changes["title"]["before"], "Old title")
        self.assertEqual(changes["title"]["after"], "New title")
        self.assertEqual(changes["description"]["before"], "Old body")
        self.assertEqual(changes["description"]["after"], "New body")
        self.assertEqual(changes["tags"]["before"], ["agenda", "general_vote"])
        self.assertEqual(changes["tags"]["after"], ["agenda", "council"])

    def test_voting_close_must_be_after_open(self):
        creator_id = uuid.uuid4()
        creator = _member(user_id=creator_id)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(creator)
        now = datetime.utcnow()
        poll = Poll(
            room_id=DEFAULT_ROOM_ID,
            id=5, group_id=1, question="q?",
            created_by_user_id=creator_id,
            voting_opens_at=now,
            deadline_at=now + timedelta(hours=1),
        )
        db = _EditDb(poll=poll)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(update_poll(
                poll_id=5,
                request=PollUpdateRequest(
                    voting_opens_at=now + timedelta(hours=2),
                    deadline_at=now + timedelta(hours=1),
                ),
                authorization="Bearer x",
                db=db,
            ))
        self.assertEqual(ctx.exception.status_code, 400)


# ── /ideas/{id} ──────────────────────────────────────────────────────────────


class TestUpdateIdeaPermissions(_EditBaseTest):
    def test_member_can_change_status_only(self):
        creator_id = uuid.uuid4()
        other = _member()
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(other)
        idea = Idea(
            room_id=DEFAULT_ROOM_ID,
            id=1, group_id=1, title="t", description="d",
            category="general", status=IdeaStatus.maybe,
            created_by_user_id=creator_id,
        )
        db = _EditDb(idea=idea)
        result = asyncio.run(update_idea(
            idea_id=1,
            request=IdeaUpdateRequest(status="planned"),
            authorization="Bearer x",
            db=db,
        ))
        self.assertEqual(result["status"], "updated")
        self.assertEqual(idea.status, IdeaStatus.planned)

    def test_member_cannot_change_title(self):
        creator_id = uuid.uuid4()
        other = _member()
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(other)
        idea = Idea(
            room_id=DEFAULT_ROOM_ID,
            id=2, group_id=1, title="t", description="d",
            category="general", status=IdeaStatus.maybe,
            created_by_user_id=creator_id,
        )
        db = _EditDb(idea=idea)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(update_idea(
                idea_id=2,
                request=IdeaUpdateRequest(title="Renamed"),
                authorization="Bearer x",
                db=db,
            ))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_creator_can_edit_tags(self):
        creator_id = uuid.uuid4()
        creator = _member(user_id=creator_id)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(creator)
        idea = Idea(
            room_id=DEFAULT_ROOM_ID,
            id=3, group_id=1, title="t", description="d",
            category="general", status=IdeaStatus.maybe,
            created_by_user_id=creator_id,
        )
        db = _EditDb(idea=idea)
        result = asyncio.run(update_idea(
            idea_id=3,
            request=IdeaUpdateRequest(tags=["fun", "weekend"]),
            authorization="Bearer x",
            db=db,
        ))
        self.assertEqual(result["status"], "updated")
        call = next(c for c in self._hub_item_calls if c.get("source_id") == 3)
        self.assertEqual(call["tags"], ["fun", "weekend"])


# ── /reminders/{id} ──────────────────────────────────────────────────────────


class TestUpdateReminderPermissionsAndHistory(_EditBaseTest):
    def test_non_creator_non_admin_rejected(self):
        creator_id = uuid.uuid4()
        other = _member()
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(other)
        reminder = Reminder(
            id=1, group_id=1, text="orig",
            room_id=DEFAULT_ROOM_ID,
            created_by_user_id=creator_id,
        )
        db = _EditDb(reminder=reminder)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(update_reminder(
                reminder_id=1,
                request=ReminderUpdateRequest(text="changed"),
                authorization="Bearer x",
                db=db,
            ))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_creator_edit_records_history(self):
        creator_id = uuid.uuid4()
        creator = _member(user_id=creator_id)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(creator)
        reminder = Reminder(
            id=2, group_id=1, text="orig",
            room_id=DEFAULT_ROOM_ID,
            created_by_user_id=creator_id,
        )
        db = _EditDb(reminder=reminder)
        asyncio.run(update_reminder(
            reminder_id=2,
            request=ReminderUpdateRequest(text="updated text", tags=["weekly"]),
            authorization="Bearer x",
            db=db,
        ))
        history_rows = [a for a in db.added if isinstance(a, ItemHistory)]
        self.assertEqual(len(history_rows), 1)
        changes = history_rows[0].changes
        self.assertEqual(changes["text"]["before"], "orig")
        self.assertEqual(changes["text"]["after"], "updated text")
        self.assertEqual(changes["tags"]["after"], ["weekly"])
        call = next(c for c in self._hub_item_calls if c.get("source_id") == 2)
        self.assertEqual(call["room_id"], DEFAULT_ROOM_ID)

    def test_room_mismatch_returns_404(self):
        creator_id = uuid.uuid4()
        creator = _member(user_id=creator_id)
        router._current_user_or_401 = lambda authorization, db, session_cookie=None: _async(creator)
        reminder = Reminder(
            id=3,
            group_id=1,
            room_id=uuid.uuid4(),
            text="orig",
            created_by_user_id=creator_id,
        )
        db = _EditDb(reminder=reminder)
        with self.assertRaises(Exception) as ctx:
            asyncio.run(update_reminder(
                reminder_id=3,
                request=ReminderUpdateRequest(text="changed"),
                authorization="Bearer x",
                db=db,
            ))
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
