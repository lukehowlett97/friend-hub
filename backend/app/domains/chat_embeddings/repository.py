"""Repositories for chat embeddings and their job queue.

Ported from app/domains/image_embeddings/repository.py — same job lifecycle
(pending → processing → completed/failed with bounded retries, claimed via
FOR UPDATE SKIP LOCKED) and the same raw-SQL pgvector access with a clear
error when pgvector is unavailable.
"""
import json
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Text as SQLText, cast, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_memory import AIMemoryEntry
from app.models.chat_embedding import ChatEmbedding, ChatEmbeddingJob
from app.models.hub_item import HubItem

EMBEDDING_JOB_STATUSES = ("pending", "processing", "completed", "failed", "skipped")

SOURCE_MESSAGE_BATCH = "message_batch"
SOURCE_MEMORY = "memory"
SOURCE_SUMMARY = "summary"
SOURCE_HUB_ITEM = "hub_item"

SUMMARY_MEMORY_TYPES = ("daily_summary", "weekly_summary")


class VectorSearchUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChatSearchResult:
    source_type: str
    source_id: str
    room_id: uuid.UUID | None
    message_start_id: int | None
    message_end_id: int | None
    content_preview: str | None
    score: float
    created_at: datetime | None


class ChatEmbeddingJobRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_pending_job(
        self,
        *,
        source_type: str,
        source_id: str,
        room_id: uuid.UUID | None = None,
        payload: dict | None = None,
    ) -> bool:
        """Enqueue a job if none exists for (source_type, source_id).

        Returns True when a new job was inserted. Raw ON CONFLICT keeps this
        idempotent even under concurrent sweeps.
        """
        result = await self.db.execute(
            text(
                """
                INSERT INTO chat_embedding_jobs
                    (source_type, source_id, room_id, payload, status, attempt_count, created_at, updated_at)
                VALUES
                    (:source_type, :source_id, :room_id, CAST(:payload AS jsonb), 'pending', 0, :now, :now)
                ON CONFLICT (source_type, source_id) DO NOTHING
                RETURNING id
                """
            ),
            {
                "source_type": source_type,
                "source_id": source_id,
                "room_id": str(room_id) if room_id else None,
                "payload": json.dumps(payload or {}),
                "now": datetime.utcnow(),
            },
        )
        return result.scalar_one_or_none() is not None

    async def claim_pending_jobs(
        self,
        *,
        limit: int,
        max_retries: int,
        room_id: uuid.UUID | None = None,
        source_types: tuple[str, ...] | None = None,
    ) -> list[ChatEmbeddingJob]:
        if limit <= 0:
            return []
        query = (
            select(ChatEmbeddingJob)
            .where(
                ChatEmbeddingJob.status == "pending",
                ChatEmbeddingJob.attempt_count < max_retries,
            )
            .order_by(ChatEmbeddingJob.created_at.asc(), ChatEmbeddingJob.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if room_id is not None:
            query = query.where(ChatEmbeddingJob.room_id == room_id)
        if source_types:
            query = query.where(ChatEmbeddingJob.source_type.in_(source_types))
        result = await self.db.execute(query)
        jobs = list(result.scalars().all())
        now = datetime.utcnow()
        for job in jobs:
            job.status = "processing"
            job.started_at = now
            job.updated_at = now
            job.last_error = None
        await self.db.flush()
        return jobs

    async def mark_completed(self, job: ChatEmbeddingJob) -> ChatEmbeddingJob:
        now = datetime.utcnow()
        job.status = "completed"
        job.completed_at = now
        job.updated_at = now
        job.last_error = None
        await self.db.flush()
        return job

    async def mark_failed(
        self,
        job: ChatEmbeddingJob,
        error: str,
        *,
        max_retries: int,
        retryable: bool = True,
    ) -> ChatEmbeddingJob:
        now = datetime.utcnow()
        job.attempt_count = (job.attempt_count or 0) + 1
        job.last_error = error[:2000]
        job.updated_at = now
        if retryable and job.attempt_count < max_retries:
            job.status = "pending"
            job.started_at = None
        else:
            job.status = "failed"
            job.completed_at = now
        await self.db.flush()
        return job

    async def mark_exhausted_pending_jobs(self, *, max_retries: int) -> int:
        result = await self.db.execute(
            select(ChatEmbeddingJob).where(
                ChatEmbeddingJob.status == "pending",
                ChatEmbeddingJob.attempt_count >= max_retries,
            )
        )
        jobs = list(result.scalars().all())
        now = datetime.utcnow()
        for job in jobs:
            job.status = "failed"
            job.completed_at = now
            job.updated_at = now
            job.last_error = job.last_error or "Maximum retry count reached"
        await self.db.flush()
        return len(jobs)

    async def status_counts(self) -> dict[str, int]:
        result = await self.db.execute(
            select(ChatEmbeddingJob.status, func.count(ChatEmbeddingJob.id))
            .group_by(ChatEmbeddingJob.status)
        )
        counts = {status: 0 for status in EMBEDDING_JOB_STATUSES}
        for status, count in result.all():
            if status in counts:
                counts[status] = int(count)
        return counts

    # ── Sweep helpers ─────────────────────────────────────────────────────────

    async def max_batched_message_end_id(self, room_id: uuid.UUID) -> int | None:
        """Highest message id already covered by a batch job (any status).

        The next batch always starts after this, so re-running the sweep can
        never enqueue an overlapping batch.
        """
        result = await self.db.execute(
            text(
                """
                SELECT MAX((payload->>'message_end_id')::int)
                FROM chat_embedding_jobs
                WHERE source_type = :source_type AND room_id = :room_id
                """
            ),
            {"source_type": SOURCE_MESSAGE_BATCH, "room_id": str(room_id)},
        )
        value = result.scalar()
        return int(value) if value is not None else None

    async def missing_memory_ids(self, *, limit: int) -> list[tuple[uuid.UUID, str]]:
        """Memory entries with no embedding job yet, as (id, source_type) pairs."""
        result = await self.db.execute(
            select(AIMemoryEntry.id, AIMemoryEntry.memory_type)
            .where(
                ~select(ChatEmbeddingJob.id)
                .where(
                    ChatEmbeddingJob.source_type.in_((SOURCE_MEMORY, SOURCE_SUMMARY)),
                    ChatEmbeddingJob.source_id == cast(AIMemoryEntry.id, SQLText),
                )
                .exists()
            )
            .order_by(AIMemoryEntry.created_at.asc())
            .limit(limit)
        )
        pairs = []
        for entry_id, memory_type in result.all():
            source_type = SOURCE_SUMMARY if memory_type in SUMMARY_MEMORY_TYPES else SOURCE_MEMORY
            pairs.append((entry_id, source_type))
        return pairs

    async def missing_hub_item_ids(self, *, limit: int) -> list[uuid.UUID]:
        """Hub items with no embedding job yet."""
        result = await self.db.execute(
            select(HubItem.id)
            .where(
                ~select(ChatEmbeddingJob.id)
                .where(
                    ChatEmbeddingJob.source_type == SOURCE_HUB_ITEM,
                    ChatEmbeddingJob.source_id == cast(HubItem.id, SQLText),
                )
                .exists()
            )
            .order_by(HubItem.created_at.asc())
            .limit(limit)
        )
        return [row[0] for row in result.all()]

    async def stale_embedded_sources(
        self, *, model_name: str, model_version: str, limit: int
    ) -> list[tuple[str, str]]:
        """Sources edited after they were last embedded, as (source_type, source_id).

        Lets the sweep requeue re-embedding for edited memories/hub items, so
        search never serves stale content for longer than one worker cycle.
        """
        stale: list[tuple[str, str]] = []

        memory_rows = await self.db.execute(
            select(ChatEmbedding.source_type, ChatEmbedding.source_id)
            .join(AIMemoryEntry, ChatEmbedding.source_id == cast(AIMemoryEntry.id, SQLText))
            .where(
                ChatEmbedding.source_type.in_((SOURCE_MEMORY, SOURCE_SUMMARY)),
                ChatEmbedding.model_name == model_name,
                ChatEmbedding.model_version == model_version,
                AIMemoryEntry.updated_at > ChatEmbedding.updated_at,
            )
            .limit(limit)
        )
        stale.extend((row[0], row[1]) for row in memory_rows.all())

        item_rows = await self.db.execute(
            select(ChatEmbedding.source_type, ChatEmbedding.source_id)
            .join(HubItem, ChatEmbedding.source_id == cast(HubItem.id, SQLText))
            .where(
                ChatEmbedding.source_type == SOURCE_HUB_ITEM,
                ChatEmbedding.model_name == model_name,
                ChatEmbedding.model_version == model_version,
                HubItem.updated_at > ChatEmbedding.updated_at,
            )
            .limit(max(0, limit - len(stale)))
        )
        stale.extend((row[0], row[1]) for row in item_rows.all())
        return stale

    async def requeue_job(
        self,
        *,
        source_type: str,
        source_id: str,
        room_id: uuid.UUID | None = None,
        payload: dict | None = None,
    ) -> bool:
        """Reset (or create) the job for a source so the worker re-embeds it.

        The embedding upsert replaces the old vector on completion, so a
        requeue can never produce duplicate embeddings.
        """
        result = await self.db.execute(
            text(
                """
                INSERT INTO chat_embedding_jobs
                    (source_type, source_id, room_id, payload, status, attempt_count, created_at, updated_at)
                VALUES
                    (:source_type, :source_id, :room_id, CAST(:payload AS jsonb), 'pending', 0, :now, :now)
                ON CONFLICT (source_type, source_id) DO UPDATE SET
                    status = 'pending',
                    attempt_count = 0,
                    last_error = NULL,
                    started_at = NULL,
                    completed_at = NULL,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """
            ),
            {
                "source_type": source_type,
                "source_id": source_id,
                "room_id": str(room_id) if room_id else None,
                "payload": json.dumps(payload or {}),
                "now": datetime.utcnow(),
            },
        )
        return result.scalar_one_or_none() is not None


class ChatEmbeddingRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_embedding(
        self,
        *,
        source_type: str,
        source_id: str,
        model_name: str,
        model_version: str,
        embedding: list[float],
        room_id: uuid.UUID | None = None,
        message_start_id: int | None = None,
        message_end_id: int | None = None,
        content_preview: str | None = None,
    ) -> int:
        """Insert or update a chat embedding using explicit pgvector casting."""
        now = datetime.utcnow()
        result = await self.db.execute(
            text(
                """
                INSERT INTO chat_embeddings (
                    source_type, source_id, room_id,
                    message_start_id, message_end_id,
                    model_name, model_version, embedding, content_preview,
                    created_at, updated_at
                )
                VALUES (
                    :source_type, :source_id, :room_id,
                    :message_start_id, :message_end_id,
                    :model_name, :model_version, CAST(:embedding AS vector), :content_preview,
                    :now, :now
                )
                ON CONFLICT (source_type, source_id, model_name, model_version)
                DO UPDATE SET
                    embedding = EXCLUDED.embedding,
                    room_id = EXCLUDED.room_id,
                    message_start_id = EXCLUDED.message_start_id,
                    message_end_id = EXCLUDED.message_end_id,
                    content_preview = EXCLUDED.content_preview,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """
            ),
            {
                "source_type": source_type,
                "source_id": source_id,
                "room_id": str(room_id) if room_id else None,
                "message_start_id": message_start_id,
                "message_end_id": message_end_id,
                "model_name": model_name,
                "model_version": model_version,
                "embedding": _vector_literal(embedding),
                "content_preview": content_preview,
                "now": now,
            },
        )
        return result.scalar_one()

    async def has_any(
        self,
        *,
        room_id: uuid.UUID | None,
        model_name: str,
        model_version: str,
    ) -> bool:
        query = select(ChatEmbedding.id).where(
            ChatEmbedding.model_name == model_name,
            ChatEmbedding.model_version == model_version,
        )
        if room_id is not None:
            query = query.where(ChatEmbedding.room_id == room_id)
        result = await self.db.execute(query.limit(1))
        return result.scalar_one_or_none() is not None

    async def search_similar(
        self,
        *,
        query_embedding: list[float],
        model_name: str,
        model_version: str,
        room_id: uuid.UUID | None = None,
        source_types: tuple[str, ...] | None = None,
        limit: int = 8,
        similarity_floor: float = 0.0,
        message_id_window: tuple[int, int] | None = None,
        date_window: tuple[datetime, datetime] | None = None,
    ) -> list[ChatSearchResult]:
        """Cosine top-k over chat embeddings, bounded and model-scoped.

        The model_name/model_version filter is mandatory: the embedding column
        is dimensionless, so mixing models in one <=> scan would error.
        """
        # The model filter also guarantees all compared vectors share a dimension.
        where = [
            "ce.model_name = :model_name",
            "ce.model_version = :model_version",
            "1 - (ce.embedding <=> CAST(:query_embedding AS vector)) >= :floor",
        ]
        params: dict = {
            "query_embedding": _vector_literal(query_embedding),
            "model_name": model_name,
            "model_version": model_version,
            "floor": similarity_floor,
            "limit": max(1, limit),
        }
        if room_id is not None:
            where.append("ce.room_id = :room_id")
            params["room_id"] = str(room_id)
        if source_types:
            placeholders = []
            for i, st in enumerate(source_types):
                key = f"source_type_{i}"
                placeholders.append(f":{key}")
                params[key] = st
            where.append(f"ce.source_type IN ({', '.join(placeholders)})")
        if message_id_window is not None:
            where.append("ce.message_start_id IS NOT NULL AND ce.message_end_id IS NOT NULL")
            where.append("ce.message_end_id >= :window_start AND ce.message_start_id <= :window_end")
            params["window_start"], params["window_end"] = message_id_window
        if date_window is not None:
            where.append("ce.created_at >= :date_from AND ce.created_at < :date_to")
            params["date_from"], params["date_to"] = date_window

        stmt = text(f"""
            SELECT
                ce.source_type,
                ce.source_id,
                ce.room_id,
                ce.message_start_id,
                ce.message_end_id,
                ce.content_preview,
                1 - (ce.embedding <=> CAST(:query_embedding AS vector)) AS score,
                ce.created_at
            FROM chat_embeddings ce
            WHERE {' AND '.join(where)}
            ORDER BY ce.embedding <=> CAST(:query_embedding AS vector)
            LIMIT :limit
        """)

        try:
            result = await self.db.execute(stmt, params)
        except SQLAlchemyError as exc:
            raise VectorSearchUnavailableError(
                "Vector chat search requires pgvector and vector-backed chat_embeddings.embedding"
            ) from exc
        except Exception as exc:
            message = str(exc).lower()
            if "vector" in message or "<=>" in message or "operator does not exist" in message:
                raise VectorSearchUnavailableError(
                    "Vector chat search requires pgvector and vector-backed chat_embeddings.embedding"
                ) from exc
            raise

        rows = result.mappings().all()
        return [
            ChatSearchResult(
                source_type=row["source_type"],
                source_id=row["source_id"],
                room_id=row["room_id"],
                message_start_id=row["message_start_id"],
                message_end_id=row["message_end_id"],
                content_preview=row["content_preview"],
                score=float(row["score"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


def _vector_literal(embedding: list[float]) -> str:
    """Convert an embedding list into pgvector literal format."""
    return "[" + ",".join(f"{value:.10g}" for value in embedding) + "]"
