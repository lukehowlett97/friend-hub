"""Tests for the shared retrieval module (semantic + date-window)."""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DEBUG", "false")

from app.domains.chat_embeddings.repository import (
    ChatSearchResult,
    VectorSearchUnavailableError,
)
from app.domains.ai.retrieval import ChatRetrievalService, RetrievedSource

ROOM = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
DAY_START = datetime(2025, 6, 1)
DAY_END = datetime(2025, 6, 2)


def _settings(**overrides):
    base = dict(
        ai_enable_chat_embeddings=True,
        ai_embedding_provider="fake",
        ai_embedding_model="fake-model",
        ai_retrieval_top_k=24,
        ai_retrieval_similarity_floor=0.25,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _make_service(*, settings=None, hits=None, has_any=True):
    svc = ChatRetrievalService.__new__(ChatRetrievalService)
    svc.db = types.SimpleNamespace(execute=AsyncMock(), get=AsyncMock(return_value=None))
    svc.settings = settings or _settings()
    svc._embed_service = types.SimpleNamespace(
        embed_query=AsyncMock(return_value=[0.1] * 8)
    )
    svc.embedding_repo = types.SimpleNamespace(
        has_any=AsyncMock(return_value=has_any),
        search_similar=AsyncMock(return_value=hits or []),
    )
    svc.memory_repo = types.SimpleNamespace(
        list_by_ids=AsyncMock(return_value=[]),
        list_entries_for_window=AsyncMock(return_value=[]),
    )
    return svc


def _hit(source_type="message_batch", source_id="r:10-12", start=10, end=12, score=0.9):
    return ChatSearchResult(
        source_type=source_type,
        source_id=source_id,
        room_id=ROOM,
        message_start_id=start,
        message_end_id=end,
        content_preview="preview",
        score=score,
        created_at=datetime(2025, 6, 1, 12, 0),
    )


def _msg_row(msg_id, content, nickname="Alice"):
    msg = types.SimpleNamespace(
        id=msg_id, content=content, is_deleted=False, is_imported=False,
        created_at=datetime(2025, 6, 1, 13, 0),
    )
    return (msg, types.SimpleNamespace(nickname=nickname), None)


class TestHasEmbeddings(unittest.TestCase):
    def test_flag_off_short_circuits(self):
        svc = _make_service(settings=_settings(ai_enable_chat_embeddings=False))
        self.assertFalse(asyncio.run(svc.has_embeddings(ROOM)))
        svc.embedding_repo.has_any.assert_not_awaited()

    def test_flag_on_checks_rows(self):
        svc = _make_service(has_any=True)
        self.assertTrue(asyncio.run(svc.has_embeddings(ROOM)))
        kwargs = svc.embedding_repo.has_any.await_args.kwargs
        self.assertEqual(kwargs["model_name"], "fake-model")
        self.assertEqual(kwargs["model_version"], "fake")


class TestRetrieveSemantic(unittest.TestCase):
    def _run(self, svc, query="camping", k=8, **kwargs):
        async def _go():
            with patch(
                "app.domains.messages.repository.MessageRepository.get_messages_in_id_range",
                new_callable=AsyncMock,
                return_value=[_msg_row(10, "let's go camping"), _msg_row(11, "yes!")],
            ):
                return await svc.retrieve_semantic(query, ROOM, k=k, **kwargs)

        return asyncio.run(_go())

    def test_k_is_clamped_and_floor_passed(self):
        svc = _make_service(hits=[])
        self._run(svc, k=50)
        kwargs = svc.embedding_repo.search_similar.await_args.kwargs
        self.assertEqual(kwargs["limit"], 24)  # clamped to ai_retrieval_top_k
        self.assertEqual(kwargs["similarity_floor"], 0.25)
        self.assertEqual(kwargs["model_name"], "fake-model")

    def test_message_batch_hydration_and_anchor(self):
        svc = _make_service(hits=[_hit()])
        sources = self._run(svc)
        self.assertEqual(len(sources), 1)
        src = sources[0]
        self.assertEqual(src.kind, "message_batch")
        self.assertEqual(src.anchor, "/chat?message=10")
        self.assertIn("let's go camping", src.text)
        self.assertEqual(src.score, 0.9)

    def test_memory_hydration(self):
        entry = types.SimpleNamespace(
            title="Pub night", memory_type="decision", content="Friday pub night.",
            created_at=datetime(2025, 6, 1), message_start_id=7, message_end_id=9,
        )
        svc = _make_service(hits=[_hit(source_type="memory", source_id=str(uuid.uuid4()), start=None, end=None)])
        svc.memory_repo.list_by_ids = AsyncMock(return_value=[entry])
        sources = self._run(svc)
        self.assertEqual(sources[0].kind, "memory")
        self.assertEqual(sources[0].anchor, "/chat?message=7")
        self.assertIn("Friday pub night.", sources[0].text)

    def test_hub_item_hydration(self):
        item = types.SimpleNamespace(
            item_type="event", short_id="E-4", title="Pub night", body="Friday 8pm",
            created_at=datetime(2025, 6, 1),
        )
        svc = _make_service(hits=[_hit(source_type="hub_item", source_id=str(uuid.uuid4()), start=None, end=None)])
        svc.db.get = AsyncMock(return_value=item)
        sources = self._run(svc)
        self.assertEqual(sources[0].anchor, "#E-4")

    def test_vector_unavailable_returns_empty(self):
        svc = _make_service()
        svc.embedding_repo.search_similar = AsyncMock(
            side_effect=VectorSearchUnavailableError("no pgvector")
        )
        self.assertEqual(self._run(svc), [])

    def test_embed_failure_returns_empty(self):
        svc = _make_service()
        svc._embed_service.embed_query = AsyncMock(side_effect=RuntimeError("down"))
        self.assertEqual(self._run(svc), [])


class TestRetrieveForDay(unittest.TestCase):
    def test_empty_day_returns_no_sources(self):
        svc = _make_service()
        # stats → (None, None, 0); every section query → empty scalars
        empty_scalars = types.SimpleNamespace(all=lambda: [])
        svc.db.execute = AsyncMock(
            return_value=types.SimpleNamespace(
                one=lambda: (None, None, 0),
                scalars=lambda: empty_scalars,
                scalar=lambda: 0,
            )
        )
        sources = asyncio.run(svc.retrieve_for_day(ROOM, DAY_START, DAY_END))
        self.assertEqual(sources, [])

    def test_day_with_messages_builds_excerpt_and_summaries_first(self):
        svc = _make_service()
        empty_scalars = types.SimpleNamespace(all=lambda: [])
        svc.db.execute = AsyncMock(
            return_value=types.SimpleNamespace(
                one=lambda: (10, 12, 3),
                scalars=lambda: empty_scalars,
                scalar=lambda: 0,
            )
        )
        entry = types.SimpleNamespace(
            title="Daily Chat Summary", memory_type="daily_summary",
            content="Camping agreed.", created_at=DAY_START,
            message_start_id=10, message_end_id=12,
        )
        svc.memory_repo.list_entries_for_window = AsyncMock(return_value=[entry])

        async def _go():
            with patch(
                "app.domains.messages.repository.MessageRepository.get_messages_in_id_range",
                new_callable=AsyncMock,
                return_value=[_msg_row(10, "camping?"), _msg_row(11, "yes"), _msg_row(12, "booked")],
            ):
                return await svc.retrieve_for_day(ROOM, DAY_START, DAY_END)

        sources = asyncio.run(_go())
        kinds = [s.kind for s in sources]
        self.assertEqual(kinds[0], "summary")  # best signal per token leads
        self.assertIn("message_batch", kinds)
        excerpt = next(s for s in sources if s.kind == "message_batch")
        self.assertEqual(excerpt.anchor, "/chat?message=10")
        self.assertIn("camping?", excerpt.text)

    def test_message_window_passed_through_to_search(self):
        svc = _make_service(hits=[])
        asyncio.run(svc.retrieve_semantic("x", ROOM, message_id_window=(10, 99)))
        kwargs = svc.embedding_repo.search_similar.await_args.kwargs
        self.assertEqual(kwargs["message_id_window"], (10, 99))


if __name__ == "__main__":
    unittest.main()
