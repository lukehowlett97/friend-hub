"""Tests for the chat embeddings pipeline: providers, jobs, sweep, worker.

All unit tests — no real database or network. Mirrors test_image_embeddings.py.
"""
import asyncio
import os
import types
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DEBUG", "false")

from app.ai.gateway import (
    FakeEmbeddingProvider,
    OllamaEmbeddingProvider,
    OpenAIEmbeddingProvider,
    get_embedding_provider,
)
from app.domains.chat_embeddings.repository import (
    SOURCE_HUB_ITEM,
    SOURCE_MEMORY,
    SOURCE_MESSAGE_BATCH,
    SOURCE_SUMMARY,
    _vector_literal,
)
from app.domains.chat_embeddings.service import ChatEmbeddingJobService, batch_source_id

ROOM = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _settings(**overrides):
    base = dict(
        ai_enable_chat_embeddings=True,
        ai_embedding_provider="fake",
        ai_embedding_model="fake-model",
        ai_embedding_api_key=None,
        ai_embedding_base_url="https://api.openai.com",
        ai_embedding_max_retries=3,
        ai_embedding_message_batch_size=5,
        ai_embedding_batch_flush_hours=6,
        ai_retrieval_top_k=24,
        ai_retrieval_similarity_floor=0.25,
        ollama_base_url="http://localhost:11434",
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ── Embedding providers ───────────────────────────────────────────────────────


class TestEmbeddingProviders(unittest.TestCase):
    def test_fake_provider_is_deterministic(self):
        provider = FakeEmbeddingProvider()
        v1, t1 = asyncio.run(provider.embed_texts(["hello world"], "any"))
        v2, _ = asyncio.run(provider.embed_texts(["hello world"], "any"))
        self.assertEqual(v1, v2)
        self.assertEqual(t1, 0)
        self.assertEqual(len(v1[0]), FakeEmbeddingProvider.DIMENSIONS)

    def test_fake_provider_differs_for_different_texts(self):
        provider = FakeEmbeddingProvider()
        (va, vb), _ = asyncio.run(provider.embed_texts(["camping trip", "tax returns"], "any"))
        self.assertNotEqual(va, vb)

    def test_fake_provider_vectors_are_normalised(self):
        provider = FakeEmbeddingProvider()
        (v,), _ = asyncio.run(provider.embed_texts(["x"], "any"))
        norm = sum(value * value for value in v) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_get_embedding_provider_selection(self):
        self.assertIsInstance(get_embedding_provider(_settings()), FakeEmbeddingProvider)
        self.assertIsInstance(
            get_embedding_provider(_settings(ai_embedding_provider="ollama")),
            OllamaEmbeddingProvider,
        )
        self.assertIsInstance(
            get_embedding_provider(
                _settings(ai_embedding_provider="openai", ai_embedding_api_key="k")
            ),
            OpenAIEmbeddingProvider,
        )

    def test_openai_provider_requires_key(self):
        with self.assertRaises(ValueError):
            get_embedding_provider(_settings(ai_embedding_provider="openai"))

    def test_unknown_provider_raises(self):
        with self.assertRaises(ValueError):
            get_embedding_provider(_settings(ai_embedding_provider="quantum"))


class TestVectorLiteral(unittest.TestCase):
    def test_formats_pgvector_literal(self):
        self.assertEqual(_vector_literal([0.5, -1.0, 0.25]), "[0.5,-1,0.25]")


# ── Job service: processing ───────────────────────────────────────────────────


def _job(source_type, source_id, payload=None, room_id=ROOM):
    return types.SimpleNamespace(
        id=1,
        source_type=source_type,
        source_id=source_id,
        room_id=room_id,
        payload=payload or {},
        status="processing",
        attempt_count=0,
    )


def _make_service(*, db=None, provider=None, settings=None):
    svc = ChatEmbeddingJobService.__new__(ChatEmbeddingJobService)
    svc.db = db or types.SimpleNamespace(execute=AsyncMock())
    svc.settings = settings or _settings()
    svc.provider = provider or FakeEmbeddingProvider()
    svc.job_repository = types.SimpleNamespace(
        create_pending_job=AsyncMock(return_value=True),
        mark_completed=AsyncMock(),
        mark_failed=AsyncMock(),
        mark_exhausted_pending_jobs=AsyncMock(return_value=0),
        claim_pending_jobs=AsyncMock(return_value=[]),
        max_batched_message_end_id=AsyncMock(return_value=None),
        missing_memory_ids=AsyncMock(return_value=[]),
        missing_hub_item_ids=AsyncMock(return_value=[]),
        stale_embedded_sources=AsyncMock(return_value=[]),
        requeue_job=AsyncMock(return_value=True),
    )
    svc.embedding_repository = types.SimpleNamespace(upsert_embedding=AsyncMock(return_value=1))
    svc.model_name = svc.settings.ai_embedding_model
    svc.model_version = svc.settings.ai_embedding_provider
    svc.max_retries = svc.settings.ai_embedding_max_retries
    return svc


def _msg_row(msg_id, content, nickname="Alice", is_deleted=False):
    msg = types.SimpleNamespace(
        id=msg_id,
        content=content,
        is_deleted=is_deleted,
        is_imported=False,
        created_at=datetime(2025, 6, 1, 13, 0, 0),
    )
    user = types.SimpleNamespace(nickname=nickname)
    return (msg, user, None)


class TestProcessJob(unittest.TestCase):
    def _run_batch_job(self, svc, rows):
        job = _job(SOURCE_MESSAGE_BATCH, batch_source_id(ROOM, 10, 12),
                   payload={"message_start_id": 10, "message_end_id": 12})

        async def _go():
            with patch(
                "app.domains.messages.repository.MessageRepository.get_messages_in_id_range",
                new_callable=AsyncMock,
                return_value=rows,
            ):
                return await svc.process_job(job)

        return asyncio.run(_go()), job

    def test_message_batch_embeds_and_completes(self):
        svc = _make_service()
        ok, job = self._run_batch_job(svc, [_msg_row(10, "camping?"), _msg_row(11, "yes!")])
        self.assertTrue(ok)
        kwargs = svc.embedding_repository.upsert_embedding.await_args.kwargs
        self.assertEqual(kwargs["source_type"], SOURCE_MESSAGE_BATCH)
        self.assertEqual(kwargs["message_start_id"], 10)
        self.assertEqual(kwargs["message_end_id"], 12)
        self.assertEqual(kwargs["model_name"], "fake-model")
        self.assertIn("camping?", kwargs["content_preview"])
        svc.job_repository.mark_completed.assert_awaited_once()
        # Usage row recorded (best-effort INSERT on the db stub)
        svc.db.execute.assert_awaited()

    def test_empty_batch_fails_non_retryably(self):
        svc = _make_service()
        ok, _ = self._run_batch_job(svc, [_msg_row(10, "", is_deleted=True)])
        self.assertFalse(ok)
        kwargs = svc.job_repository.mark_failed.await_args.kwargs
        self.assertFalse(kwargs["retryable"])
        svc.embedding_repository.upsert_embedding.assert_not_awaited()

    def test_memory_job_uses_entry_text_and_range(self):
        entry = types.SimpleNamespace(
            memory_type="decision", title="Pub night", content="Friday is pub night.",
            room_id=ROOM, message_start_id=5, message_end_id=9,
        )
        svc = _make_service(db=types.SimpleNamespace(
            execute=AsyncMock(), get=AsyncMock(return_value=entry)
        ))
        job = _job(SOURCE_MEMORY, str(uuid.uuid4()))
        ok = asyncio.run(svc.process_job(job))
        self.assertTrue(ok)
        kwargs = svc.embedding_repository.upsert_embedding.await_args.kwargs
        self.assertIn("Friday is pub night.", kwargs["content_preview"])
        self.assertEqual(kwargs["message_start_id"], 5)

    def test_missing_memory_row_fails_non_retryably(self):
        svc = _make_service(db=types.SimpleNamespace(
            execute=AsyncMock(), get=AsyncMock(return_value=None)
        ))
        ok = asyncio.run(svc.process_job(_job(SOURCE_SUMMARY, str(uuid.uuid4()))))
        self.assertFalse(ok)
        self.assertFalse(svc.job_repository.mark_failed.await_args.kwargs["retryable"])

    def test_hub_item_job(self):
        item = types.SimpleNamespace(
            item_type="event", short_id="E-4", title="Pub night", body="Friday 8pm",
            room_id=ROOM,
        )
        svc = _make_service(db=types.SimpleNamespace(
            execute=AsyncMock(), get=AsyncMock(return_value=item)
        ))
        ok = asyncio.run(svc.process_job(_job(SOURCE_HUB_ITEM, str(uuid.uuid4()))))
        self.assertTrue(ok)
        kwargs = svc.embedding_repository.upsert_embedding.await_args.kwargs
        self.assertIn("E-4", kwargs["content_preview"])

    def test_provider_failure_is_retryable(self):
        class _ExplodingProvider:
            async def embed_texts(self, texts, model):
                raise RuntimeError("ollama down")

        svc = _make_service(provider=_ExplodingProvider())
        ok, _ = self._run_batch_job(svc, [_msg_row(10, "hello")])
        self.assertFalse(ok)
        kwargs = svc.job_repository.mark_failed.await_args.kwargs
        self.assertTrue(kwargs["retryable"])


# ── Sweep enqueuer ────────────────────────────────────────────────────────────


class TestEnqueueSweep(unittest.TestCase):
    def _make(self, message_rows, last_end=None, settings=None):
        db = types.SimpleNamespace(
            execute=AsyncMock(return_value=types.SimpleNamespace(all=lambda: message_rows))
        )
        svc = _make_service(db=db, settings=settings)
        svc.job_repository.max_batched_message_end_id = AsyncMock(return_value=last_end)
        return svc

    @staticmethod
    def _rows(ids, created_at=None):
        created = created_at or (datetime.utcnow() - timedelta(days=1))
        return [(i, created) for i in ids]

    def test_full_batches_enqueued(self):
        svc = self._make(self._rows(range(1, 11)))  # 10 msgs, batch size 5
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=ROOM))
        self.assertEqual(enqueued, 2)
        calls = svc.job_repository.create_pending_job.await_args_list
        first = calls[0].kwargs
        self.assertEqual(first["source_type"], SOURCE_MESSAGE_BATCH)
        self.assertEqual(first["payload"], {"message_start_id": 1, "message_end_id": 5})
        second = calls[1].kwargs
        self.assertEqual(second["payload"], {"message_start_id": 6, "message_end_id": 10})

    def test_fresh_partial_tail_is_left_for_later(self):
        svc = self._make(self._rows([1, 2, 3, 4], created_at=datetime.utcnow()))
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=None))
        self.assertEqual(enqueued, 0)

    def test_aged_partial_tail_is_flushed(self):
        old = datetime.utcnow() - timedelta(hours=12)
        svc = self._make(self._rows([1, 2, 3, 4], created_at=old))
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=ROOM))
        self.assertEqual(enqueued, 1)
        payload = svc.job_repository.create_pending_job.await_args.kwargs["payload"]
        self.assertEqual(payload, {"message_start_id": 1, "message_end_id": 4})

    def test_tiny_tail_never_flushed(self):
        old = datetime.utcnow() - timedelta(hours=12)
        svc = self._make(self._rows([1, 2], created_at=old))
        self.assertEqual(asyncio.run(svc.enqueue_sweep(room_id=ROOM)), 0)

    def test_rerun_counts_nothing_when_jobs_exist(self):
        # create_pending_job returning False (ON CONFLICT DO NOTHING) → not counted
        svc = self._make(self._rows(range(1, 11)))
        svc.job_repository.create_pending_job = AsyncMock(return_value=False)
        self.assertEqual(asyncio.run(svc.enqueue_sweep(room_id=ROOM)), 0)

    def test_stale_sources_are_requeued(self):
        svc = self._make([])
        svc.job_repository.stale_embedded_sources = AsyncMock(
            return_value=[(SOURCE_HUB_ITEM, "abc"), (SOURCE_MEMORY, "def")]
        )
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=None))
        self.assertEqual(enqueued, 2)
        calls = svc.job_repository.requeue_job.await_args_list
        self.assertEqual(
            [(c.kwargs["source_type"], c.kwargs["source_id"]) for c in calls],
            [(SOURCE_HUB_ITEM, "abc"), (SOURCE_MEMORY, "def")],
        )
        # Stale query is scoped to the active model so other models' rows are ignored
        kwargs = svc.job_repository.stale_embedded_sources.await_args.kwargs
        self.assertEqual(kwargs["model_name"], "fake-model")
        self.assertEqual(kwargs["model_version"], "fake")

    def test_room_scoped_sweep_skips_global_stale_sources(self):
        svc = self._make([])
        svc.job_repository.stale_embedded_sources = AsyncMock(
            return_value=[(SOURCE_HUB_ITEM, "abc"), (SOURCE_MEMORY, "def")]
        )
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=ROOM))
        self.assertEqual(enqueued, 0)
        svc.job_repository.stale_embedded_sources.assert_not_awaited()

    def test_memory_and_hub_item_anti_joins(self):
        svc = self._make([])
        mem_id, item_id = uuid.uuid4(), uuid.uuid4()
        svc.job_repository.missing_memory_ids = AsyncMock(
            return_value=[(mem_id, SOURCE_SUMMARY)]
        )
        svc.job_repository.missing_hub_item_ids = AsyncMock(return_value=[item_id])
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=None))
        self.assertEqual(enqueued, 2)
        types_used = [
            c.kwargs["source_type"]
            for c in svc.job_repository.create_pending_job.await_args_list
        ]
        self.assertEqual(types_used, [SOURCE_SUMMARY, SOURCE_HUB_ITEM])

    def test_room_scoped_sweep_skips_global_memory_and_hub_items(self):
        svc = self._make([])
        mem_id, item_id = uuid.uuid4(), uuid.uuid4()
        svc.job_repository.missing_memory_ids = AsyncMock(
            return_value=[(mem_id, SOURCE_SUMMARY)]
        )
        svc.job_repository.missing_hub_item_ids = AsyncMock(return_value=[item_id])
        enqueued = asyncio.run(svc.enqueue_sweep(room_id=ROOM))
        self.assertEqual(enqueued, 0)
        svc.job_repository.missing_memory_ids.assert_not_awaited()
        svc.job_repository.missing_hub_item_ids.assert_not_awaited()


# ── Worker ────────────────────────────────────────────────────────────────────


class TestWorkerRunOnce(unittest.TestCase):
    def test_run_once_sweeps_claims_and_processes(self):
        from app.domains.chat_embeddings import worker

        fake_service = types.SimpleNamespace(
            enqueue_sweep=AsyncMock(return_value=3),
            claim_pending_jobs=AsyncMock(return_value=[_job(SOURCE_MEMORY, "x")]),
            process_job=AsyncMock(return_value=True),
            job_repository=types.SimpleNamespace(mark_failed=AsyncMock()),
            max_retries=3,
        )

        class _FakeSessionCtx:
            async def __aenter__(self):
                return types.SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

            async def __aexit__(self, *args):
                return False

        async def _go():
            with patch.object(worker, "async_session_factory", lambda: _FakeSessionCtx()), \
                 patch.object(worker, "ChatEmbeddingJobService", lambda db: fake_service):
                return await worker.run_once(limit=10)

        enqueued, processed = asyncio.run(_go())
        self.assertEqual((enqueued, processed), (3, 1))
        fake_service.claim_pending_jobs.assert_awaited_once_with(
            limit=10, room_id=None, source_types=None
        )
        fake_service.process_job.assert_awaited_once()

    def test_run_once_room_scope_claims_only_message_batches(self):
        from app.domains.chat_embeddings import worker

        fake_service = types.SimpleNamespace(
            enqueue_sweep=AsyncMock(return_value=1),
            claim_pending_jobs=AsyncMock(return_value=[]),
            job_repository=types.SimpleNamespace(mark_failed=AsyncMock()),
            max_retries=3,
        )

        class _FakeSessionCtx:
            async def __aenter__(self):
                return types.SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

            async def __aexit__(self, *args):
                return False

        async def _go():
            with patch.object(worker, "async_session_factory", lambda: _FakeSessionCtx()), \
                 patch.object(worker, "ChatEmbeddingJobService", lambda db: fake_service):
                return await worker.run_once(limit=10, room_id=ROOM)

        asyncio.run(_go())
        fake_service.enqueue_sweep.assert_awaited_once_with(room_id=ROOM)
        fake_service.claim_pending_jobs.assert_awaited_once_with(
            limit=10, room_id=ROOM, source_types=(SOURCE_MESSAGE_BATCH,)
        )

    def test_run_worker_survives_tick_failures(self):
        from app.domains.chat_embeddings import worker

        calls = {"n": 0}

        async def _flaky_run_once(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db connection dropped")
            return 0, 0  # backfill exits on (0, 0)

        async def _no_sleep(_seconds):
            return None

        fake_settings = types.SimpleNamespace(
            ai_enable_chat_embeddings=True,
            ai_embedding_provider="fake",
            ai_embedding_model="fake-model",
        )

        async def _go():
            with patch.object(worker, "run_once", _flaky_run_once), \
                 patch.object(worker, "get_settings", lambda: fake_settings), \
                 patch.object(worker.asyncio, "sleep", _no_sleep):
                await worker.run_worker(once=False, limit=10, sleep_seconds=1, backfill=True)

        asyncio.run(_go())
        self.assertEqual(calls["n"], 2)  # failed once, retried, completed

    def test_run_worker_disabled_flag_exits_immediately(self):
        from app.domains.chat_embeddings import worker

        fake_settings = types.SimpleNamespace(ai_enable_chat_embeddings=False)
        ran = AsyncMock()

        async def _go():
            with patch.object(worker, "get_settings", lambda: fake_settings), \
                 patch.object(worker, "run_once", ran):
                await worker.run_worker(once=False, limit=10, sleep_seconds=1)

        asyncio.run(_go())
        ran.assert_not_awaited()

    def test_run_once_no_sweep(self):
        from app.domains.chat_embeddings import worker

        fake_service = types.SimpleNamespace(
            enqueue_sweep=AsyncMock(),
            claim_pending_jobs=AsyncMock(return_value=[]),
            job_repository=types.SimpleNamespace(mark_failed=AsyncMock()),
            max_retries=3,
        )

        class _FakeSessionCtx:
            async def __aenter__(self):
                return types.SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

            async def __aexit__(self, *args):
                return False

        async def _go():
            with patch.object(worker, "async_session_factory", lambda: _FakeSessionCtx()), \
                 patch.object(worker, "ChatEmbeddingJobService", lambda db: fake_service):
                return await worker.run_once(limit=10, sweep=False)

        enqueued, processed = asyncio.run(_go())
        self.assertEqual((enqueued, processed), (0, 0))
        fake_service.enqueue_sweep.assert_not_awaited()


# ── Admin status endpoint ─────────────────────────────────────────────────────


class TestStatusEndpoint(unittest.TestCase):
    def _call(self, *, is_owner=True):
        from app.api.v1 import chat_embeddings_router as mod

        last = datetime(2026, 6, 12, 0, 53, 0)
        db = types.SimpleNamespace(
            execute=AsyncMock(
                return_value=types.SimpleNamespace(
                    one=lambda: (663, last),
                    scalar=lambda: last,
                )
            )
        )

        async def _go():
            with patch.object(mod, "_current_user_or_401", AsyncMock(return_value=object())), \
                 patch.object(mod, "_is_owner_user", lambda user: is_owner), \
                 patch.object(
                     mod.ChatEmbeddingJobRepository,
                     "status_counts",
                     AsyncMock(return_value={"pending": 0, "processing": 0, "completed": 663, "failed": 0, "skipped": 0}),
                 ), patch.object(
                     mod,
                     "get_settings",
                     lambda: types.SimpleNamespace(
                         ai_enable_chat_embeddings=True,
                         ai_embedding_provider="ollama",
                         ai_embedding_model="nomic-embed-text",
                         ai_retrieval_similarity_floor=0.45,
                     ),
                 ):
                return await mod.chat_embedding_status(authorization="Bearer x", db=db)

        return asyncio.run(_go())

    def test_status_payload(self):
        payload = self._call()
        self.assertTrue(payload["enabled"])
        self.assertEqual(payload["provider"], "ollama")
        self.assertEqual(payload["model"], "nomic-embed-text")
        self.assertEqual(payload["total_embeddings"], 663)
        self.assertEqual(payload["jobs"]["completed"], 663)
        self.assertIn("last_processed_at", payload)
        self.assertEqual(payload["similarity_floor"], 0.45)

    def test_non_owner_gets_403(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self._call(is_owner=False)
        self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
