"""Tests for per-user chat read-state tracking.

All tests are unit tests — no real database. The repository is exercised
against a stub session that records adds and returns scripted rows.
"""
import asyncio
import os
import types
import unittest
import uuid

os.environ.setdefault("DEBUG", "false")

from app.domains.chat.read_state_repository import ChatReadStateRepository
from app.models.chat_read_state import ChatReadState

USER = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
ROOM = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


class _StubDb:
    def __init__(self, existing=None, count=0):
        self.existing = existing
        self.count = count
        self.added = []
        self.statements = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def execute(self, stmt):
        self.statements.append(stmt)
        return types.SimpleNamespace(
            scalar_one_or_none=lambda: self.existing,
            scalar=lambda: self.count,
        )


class TestUpsertForward(unittest.TestCase):
    def test_creates_state_when_none_exists(self):
        db = _StubDb(existing=None)
        repo = ChatReadStateRepository(db)
        state = asyncio.run(repo.upsert_forward(USER, ROOM, 42))
        self.assertEqual(state.last_read_message_id, 42)
        self.assertEqual(len(db.added), 1)
        self.assertIs(db.added[0], state)

    def test_moves_forward(self):
        existing = ChatReadState(user_id=USER, room_id=ROOM, last_read_message_id=10)
        db = _StubDb(existing=existing)
        repo = ChatReadStateRepository(db)
        state = asyncio.run(repo.upsert_forward(USER, ROOM, 42))
        self.assertEqual(state.last_read_message_id, 42)
        self.assertEqual(db.added, [])

    def test_never_moves_backwards(self):
        existing = ChatReadState(user_id=USER, room_id=ROOM, last_read_message_id=50)
        db = _StubDb(existing=existing)
        repo = ChatReadStateRepository(db)
        state = asyncio.run(repo.upsert_forward(USER, ROOM, 42))
        self.assertEqual(state.last_read_message_id, 50)
        self.assertEqual(db.added, [])

    def test_equal_id_is_a_noop(self):
        existing = ChatReadState(user_id=USER, room_id=ROOM, last_read_message_id=42)
        existing.updated_at = None
        db = _StubDb(existing=existing)
        repo = ChatReadStateRepository(db)
        state = asyncio.run(repo.upsert_forward(USER, ROOM, 42))
        self.assertEqual(state.last_read_message_id, 42)
        self.assertIsNone(state.updated_at)  # untouched — no write happened


class TestCountMessagesAfter(unittest.TestCase):
    def test_returns_scalar_count(self):
        db = _StubDb(count=7)
        repo = ChatReadStateRepository(db)
        self.assertEqual(asyncio.run(repo.count_messages_after(ROOM, 10)), 7)

    def test_filters_by_id_only_when_given(self):
        db = _StubDb(count=0)
        repo = ChatReadStateRepository(db)
        asyncio.run(repo.count_messages_after(ROOM, 10))
        asyncio.run(repo.count_messages_after(ROOM, None))
        with_id, without_id = (str(s) for s in db.statements)
        self.assertIn("messages.id >", with_id)
        self.assertNotIn("messages.id >", without_id)
        # Deleted messages never count as unread
        self.assertIn("is_deleted", with_id)


if __name__ == "__main__":
    unittest.main()
