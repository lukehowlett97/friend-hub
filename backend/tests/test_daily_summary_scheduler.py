"""Tests for the scheduled daily summary job.

All tests are unit tests — DB calls and HubSummaryService are stubbed.
"""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DEBUG", "false")

from app.domains.ai.daily_summary_scheduler import _run_once, _summarize_room_day

ROOM = types.SimpleNamespace(
    id=uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002"),
    slug="the-lads",
    status="active",
)
DAY_START = datetime(2024, 6, 14)
DAY_END = datetime(2024, 6, 15)


class _StubDb:
    """execute() yields the scripted message-id range, then rooms if asked."""

    def __init__(self, id_range=(None, None), rooms=None):
        self.id_range = id_range
        self.rooms = rooms or []
        self.committed = False
        self.rolled_back = False

    async def execute(self, stmt):
        text = str(stmt)
        if "rooms" in text:
            rooms = self.rooms
            return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: rooms))
        return types.SimpleNamespace(one=lambda: self.id_range)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _settings(enabled=True, api_key="key"):
    return types.SimpleNamespace(ai_daily_summary_enabled=enabled, ai_api_key=api_key)


def _run_room_day(db, exists=False):
    summarize = AsyncMock(return_value={"summary": "ok"})

    async def _go():
        with patch(
            "app.domains.ai.repository.AIMemoryRepository.exists_daily_summary_overlapping",
            new_callable=AsyncMock,
            return_value=exists,
        ) as exists_mock, patch(
            "app.domains.ai.summary_service.HubSummaryService.summarize_chat",
            summarize,
        ), patch(
            "app.domains.ai.summary_service.create_llm_client",
            return_value=types.SimpleNamespace(),
        ):
            ran = await _summarize_room_day(db, ROOM, DAY_START, DAY_END)
            return ran, exists_mock

    ran, exists_mock = asyncio.run(_go())
    return ran, summarize, exists_mock


class TestSummarizeRoomDay(unittest.TestCase):
    def test_summarises_room_with_messages(self):
        db = _StubDb(id_range=(10, 99))
        ran, summarize, _ = _run_room_day(db)
        self.assertTrue(ran)
        self.assertTrue(db.committed)
        kwargs = summarize.await_args.kwargs
        self.assertEqual(kwargs["room_id"], ROOM.id)
        self.assertEqual(kwargs["start_at"], DAY_START)
        self.assertEqual(kwargs["end_at"], DAY_END)
        self.assertEqual(kwargs["created_by"], "daily_summary_job")

    def test_idempotent_when_summary_already_exists(self):
        db = _StubDb(id_range=(10, 99))
        ran, summarize, exists_mock = _run_room_day(db, exists=True)
        self.assertFalse(ran)
        summarize.assert_not_awaited()
        exists_mock.assert_awaited_once_with(ROOM.id, 10, 99)

    def test_room_with_no_messages_is_skipped(self):
        db = _StubDb(id_range=(None, None))
        ran, summarize, exists_mock = _run_room_day(db)
        self.assertFalse(ran)
        summarize.assert_not_awaited()
        exists_mock.assert_not_awaited()


class TestRunOnce(unittest.TestCase):
    def _run(self, settings, db=None):
        async def _go():
            with patch("app.config.get_settings", return_value=settings):
                return await _run_once(db or _StubDb())

        return asyncio.run(_go())

    def test_disabled_flag_short_circuits(self):
        self.assertEqual(self._run(_settings(enabled=False)), 0)

    def test_missing_api_key_short_circuits(self):
        self.assertEqual(self._run(_settings(api_key=None)), 0)

    def test_one_room_failure_does_not_block_others(self):
        room_b = types.SimpleNamespace(id=uuid.uuid4(), slug="other", status="active")
        db = _StubDb(id_range=(10, 99), rooms=[ROOM, room_b])
        calls = []

        async def _flaky(db_, room, day_start, day_end):
            calls.append(room.slug)
            if room.slug == "the-lads":
                raise RuntimeError("LLM down")
            return True

        async def _go():
            with patch("app.config.get_settings", return_value=_settings()), patch(
                "app.domains.ai.daily_summary_scheduler._summarize_room_day",
                _flaky,
            ):
                return await _run_once(db)

        count = asyncio.run(_go())
        self.assertEqual(calls, ["the-lads", "other"])
        self.assertEqual(count, 1)
        self.assertTrue(db.rolled_back)


if __name__ == "__main__":
    unittest.main()
