"""Tests for the /catchup command.

All tests are unit tests — no real database or network calls. CatchupService
repositories are replaced with stubs; the LLM is the same scripted fake the
summarise tests use.
"""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DEBUG", "false")

from app.domains.ai.capabilities import is_catchup_query
from app.domains.ai.catchup_service import (
    CATCHUP_MAX_RAW_MESSAGES,
    CatchupService,
)
from app.domains.ai.hub_agent_service import HubAgentResult, SharedHubBotService

USER = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
ROOM = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _msg(msg_id, content, nickname="Alice"):
    return {
        "id": msg_id,
        "nickname": nickname,
        "is_bot": False,
        "is_deleted": False,
        "content": content,
        "created_at": datetime(2024, 6, 15, 13, 0, 0),
        "type": "chat",
    }


class _FakeLLM:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self, reply="• Stuff happened."):
        self.reply = reply
        self.calls = []

    def _get_provider(self):
        return self

    async def complete_chat(self, messages, model, temperature=0.3):
        self.calls.append(messages)
        return self.reply, 10, 5


def _make_service(
    llm=None,
    read_state=None,
    message_count=0,
    summaries=None,
    appendix=None,
):
    svc = CatchupService.__new__(CatchupService)
    svc.db = types.SimpleNamespace(
        execute=AsyncMock(
            return_value=types.SimpleNamespace(scalar=lambda: message_count)
        )
    )
    svc.llm_client = llm or _FakeLLM()
    svc.read_state_repo = types.SimpleNamespace(
        get=AsyncMock(return_value=read_state),
        count_messages_after=AsyncMock(return_value=message_count),
    )
    last_read = types.SimpleNamespace(created_at=datetime(2024, 6, 14, 19, 40, 0))
    svc.message_repo = types.SimpleNamespace(
        get_message_by_id=AsyncMock(return_value=last_read),
    )
    svc.memory_repo = types.SimpleNamespace(
        list_summaries_for_gap=AsyncMock(return_value=summaries or []),
    )
    svc._build_appendix = AsyncMock(return_value=appendix or [])
    return svc


def _read_state(last_read_message_id=100):
    return types.SimpleNamespace(last_read_message_id=last_read_message_id)


def _run_catchup(svc, user_id=USER, room_id=ROOM, override_window=None, messages=None):
    async def _go():
        with patch(
            "app.services.chat_service.ChatService.get_recent_messages",
            new_callable=AsyncMock,
            return_value=messages or [],
        ):
            return await svc.build_catchup(user_id, room_id, override_window)

    return asyncio.run(_go())


# ── Nothing missed ────────────────────────────────────────────────────────────


class TestNothingMissed(unittest.TestCase):
    def test_friendly_one_liner_without_llm_call(self):
        llm = _FakeLLM()
        svc = _make_service(llm=llm, read_state=_read_state(), message_count=0)
        result = _run_catchup(svc)
        self.assertIn("all caught up", result.reply)
        self.assertFalse(result.used_llm)
        self.assertEqual(llm.calls, [])  # acceptance criterion: no LLM call wasted

    def test_appendix_alone_still_replies_without_narrative(self):
        llm = _FakeLLM()
        svc = _make_service(
            llm=llm,
            read_state=_read_state(),
            message_count=0,
            appendix=['• Poll #P-6 "BBQ or beach?" — you haven\'t voted.'],
        )
        result = _run_catchup(svc)
        self.assertIn("#P-6", result.reply)
        self.assertEqual(llm.calls, [])


# ── Small vs large gap strategies ─────────────────────────────────────────────


class TestGapStrategies(unittest.TestCase):
    def test_small_gap_feeds_raw_messages_to_llm(self):
        llm = _FakeLLM("• Pub night planned.")
        svc = _make_service(llm=llm, read_state=_read_state(), message_count=3)
        result = _run_catchup(svc, messages=[_msg(101, "Friday pub night?")])
        self.assertTrue(result.used_llm)
        self.assertFalse(result.used_summaries)
        prompt = llm.calls[0][1]["content"]
        self.assertIn("Friday pub night?", prompt)

    def test_large_gap_uses_stored_summaries_not_full_history(self):
        llm = _FakeLLM("• Big week.")
        summary = types.SimpleNamespace(
            created_at=datetime(2024, 6, 14),
            title="Daily Chat Summary",
            memory_type="daily_summary",
            content="Lakes trip booked.",
        )
        svc = _make_service(
            llm=llm,
            read_state=_read_state(),
            message_count=CATCHUP_MAX_RAW_MESSAGES + 1,
            summaries=[summary],
        )
        result = _run_catchup(svc, messages=[_msg(500, "tail message")])
        self.assertTrue(result.used_summaries)
        prompt = llm.calls[0][1]["content"]
        self.assertIn("STORED SUMMARIES", prompt)
        self.assertIn("Lakes trip booked.", prompt)
        svc.memory_repo.list_summaries_for_gap.assert_awaited_once()

    def test_no_read_state_falls_back_to_24_hours(self):
        svc = _make_service(read_state=None, message_count=0)
        result = _run_catchup(svc)
        # Gap start comes from the 24h fallback, not the (absent) read state
        svc.message_repo.get_message_by_id.assert_not_awaited()
        self.assertEqual(result.message_count, 0)

    def test_reply_contains_header_and_footer(self):
        svc = _make_service(read_state=_read_state(), message_count=2)
        result = _run_catchup(svc, messages=[_msg(101, "hello")])
        self.assertIn("Since you were last here", result.reply)
        self.assertIn("2 messages", result.reply)
        self.assertIn("/summarise since", result.reply)

    def test_appendix_lines_survive_verbatim(self):
        appendix = [
            '• Poll #P-6 "BBQ or beach?" — you haven\'t voted.',
            '• Event #E-4 "Pub night" — created while you were away.',
        ]
        svc = _make_service(read_state=_read_state(), message_count=2, appendix=appendix)
        result = _run_catchup(svc, messages=[_msg(101, "hello")])
        for line in appendix:
            self.assertIn(line, result.reply)


# ── summarize_chat range metadata ─────────────────────────────────────────────


class TestSummarizeChatRange(unittest.TestCase):
    def test_memories_carry_room_and_message_range(self):
        from app.domains.ai.summary_service import FakeLLMClient, HubSummaryService

        svc = HubSummaryService.__new__(HubSummaryService)
        svc.db = types.SimpleNamespace()
        svc.llm_client = FakeLLMClient()
        svc.run_repo = types.SimpleNamespace(
            create=AsyncMock(return_value=types.SimpleNamespace(id=uuid.uuid4())),
            update=AsyncMock(),
            mark_completed=AsyncMock(),
            mark_failed=AsyncMock(),
        )
        created = []

        async def _create(**kwargs):
            created.append(kwargs)
            return types.SimpleNamespace(id=uuid.uuid4(), **kwargs)

        svc.memory_repo = types.SimpleNamespace(create=_create)
        svc.suggestion_repo = types.SimpleNamespace(
            create=AsyncMock(return_value=types.SimpleNamespace(id=uuid.uuid4()))
        )
        svc._build_hub_items_text = AsyncMock(return_value="")
        svc._build_existing_memories_text = AsyncMock(return_value="")

        messages = [_msg(7, "morning"), _msg(12, "afternoon"), _msg(9, "midday")]

        async def _go():
            with patch(
                "app.services.chat_service.ChatService.get_recent_messages",
                new_callable=AsyncMock,
                return_value=messages,
            ) as fetch:
                result = await svc.summarize_chat(
                    room_id=ROOM,
                    start_at=datetime(2024, 6, 14),
                    end_at=datetime(2024, 6, 15),
                    created_by="daily_summary_job",
                )
                return result, fetch

        result, fetch = asyncio.run(_go())
        self.assertGreaterEqual(len(created), 1)
        for kwargs in created:
            self.assertEqual(kwargs["room_id"], ROOM)
            self.assertEqual(kwargs["message_start_id"], 7)
            self.assertEqual(kwargs["message_end_id"], 12)
            self.assertEqual(kwargs["created_by"], "daily_summary_job")
        fetch_kwargs = fetch.await_args.kwargs
        self.assertEqual(fetch_kwargs["room_id"], ROOM)
        self.assertEqual(fetch_kwargs["start_at"], datetime(2024, 6, 14))
        self.assertEqual(fetch_kwargs["end_at"], datetime(2024, 6, 15))


# ── Dispatch from process_query ───────────────────────────────────────────────


class _StubRunRepo:
    async def create(self, **kw):
        return types.SimpleNamespace(id=uuid.uuid4())

    async def mark_completed(self, **kw):
        pass

    async def mark_failed(self, **kw):
        pass


def _make_hub_service():
    svc = SharedHubBotService.__new__(SharedHubBotService)
    svc.db = types.SimpleNamespace()
    svc.llm_client = _FakeLLM()
    svc.run_repo = _StubRunRepo()
    svc.memory_repo = types.SimpleNamespace()
    svc.suggestion_repo = types.SimpleNamespace()
    svc.registry = types.SimpleNamespace(list_tools=lambda: [])
    return svc


class TestDispatch(unittest.TestCase):
    def _process(self, query):
        svc = _make_hub_service()
        handled = {}

        async def _fake_handler(arg, run, start_time, include_debug, room_id=None, user_id=None):
            handled["arg"] = arg
            return HubAgentResult(reply="caught up", command="catchup")

        svc._handle_catchup = _fake_handler
        result = asyncio.run(
            svc.process_query(query, user_id=USER, room_id=ROOM, source="chat")
        )
        return result, handled

    def test_slash_catchup_routes_to_handler(self):
        result, handled = self._process("/catchup")
        self.assertEqual(result.command, "catchup")
        self.assertEqual(handled["arg"], "")

    def test_slash_catchup_with_window_passes_arg(self):
        result, handled = self._process("/catchup since 14:00")
        self.assertEqual(handled["arg"], "since 14:00")

    def test_what_did_i_miss_routes_to_handler(self):
        result, handled = self._process("what did I miss?")
        self.assertEqual(result.command, "catchup")

    def test_phrases(self):
        for q in ("/catchup", "What did I miss?", "catch me up", "anything I missed?"):
            self.assertTrue(is_catchup_query(q), q)
        for q in ("I miss summer", "summarise camping", "did you catch the game", ""):
            self.assertFalse(is_catchup_query(q), q)


if __name__ == "__main__":
    unittest.main()
