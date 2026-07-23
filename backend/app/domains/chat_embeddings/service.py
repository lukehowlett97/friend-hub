"""Chat embedding job service: sweep enqueueing, job processing, query embedding.

Mirrors PhotoEmbeddingJobService. The sweep is the single enqueue path for
both historical backfill and steady-state: it batches unembedded messages per
room and anti-joins memories/summaries/hub items against the job table, so
re-running it after an interruption never duplicates work.
"""
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.gateway import get_embedding_provider
from app.config import get_settings
from app.domains.chat_embeddings.repository import (
    SOURCE_HUB_ITEM,
    SOURCE_MEMORY,
    SOURCE_MESSAGE_BATCH,
    SOURCE_SUMMARY,
    ChatEmbeddingJobRepository,
    ChatEmbeddingRepository,
)
from app.models.ai_memory import AIMemoryEntry
from app.models.chat_embedding import ChatEmbeddingJob
from app.models.hub_item import HubItem
from app.models.message import Message
from app.models.room import Room

logger = logging.getLogger(__name__)

CONTENT_PREVIEW_CHARS = 200
MIN_TAIL_BATCH_SIZE = 3


def batch_source_id(room_id: uuid.UUID, start_id: int, end_id: int) -> str:
    return f"{room_id}:{start_id}-{end_id}"


class ChatEmbeddingJobService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        provider=None,
        settings=None,
        job_repository: ChatEmbeddingJobRepository | None = None,
        embedding_repository: ChatEmbeddingRepository | None = None,
    ):
        self.db = db
        self.settings = settings or get_settings()
        self.provider = provider or get_embedding_provider(self.settings)
        self.job_repository = job_repository or ChatEmbeddingJobRepository(db)
        self.embedding_repository = embedding_repository or ChatEmbeddingRepository(db)
        self.model_name = self.settings.ai_embedding_model
        self.model_version = self.settings.ai_embedding_provider
        self.max_retries = self.settings.ai_embedding_max_retries

    # ── Sweep enqueueing (backfill == steady-state) ───────────────────────────

    async def enqueue_sweep(self, *, room_id: uuid.UUID | None = None, max_new_jobs: int = 200) -> int:
        """Enqueue embedding jobs for anything not yet covered. Idempotent."""
        enqueued = 0
        batch_size = self.settings.ai_embedding_message_batch_size

        rooms = await self._active_room_ids(room_id)
        for rid in rooms:
            if enqueued >= max_new_jobs:
                return enqueued
            enqueued += await self._enqueue_message_batches(
                rid, batch_size, max_new_jobs - enqueued
            )

        if room_id is None:
            for entry_id, source_type in await self.job_repository.missing_memory_ids(
                limit=max(0, max_new_jobs - enqueued)
            ):
                if await self.job_repository.create_pending_job(
                    source_type=source_type, source_id=str(entry_id)
                ):
                    enqueued += 1

            for item_id in await self.job_repository.missing_hub_item_ids(
                limit=max(0, max_new_jobs - enqueued)
            ):
                if await self.job_repository.create_pending_job(
                    source_type=SOURCE_HUB_ITEM, source_id=str(item_id)
                ):
                    enqueued += 1

        if room_id is None:
            # Re-embed sources edited since their last embedding (self-healing:
            # anything missed here is picked up again on the next sweep).
            stale = await self._stale_sources(limit=max(0, max_new_jobs - enqueued))
            for source_type, source_id in stale:
                if await self.job_repository.requeue_job(
                    source_type=source_type, source_id=source_id
                ):
                    enqueued += 1
                    logger.info("Requeued stale embedding %s:%s", source_type, source_id)

        return enqueued

    async def _stale_sources(self, *, limit: int) -> list[tuple[str, str]]:
        if limit <= 0:
            return []
        return await self.job_repository.stale_embedded_sources(
            model_name=self.model_name,
            model_version=self.model_version,
            limit=limit,
        )

    async def _active_room_ids(self, room_id: uuid.UUID | None) -> list[uuid.UUID]:
        if room_id is not None:
            return [room_id]
        result = await self.db.execute(select(Room.id).where(Room.status == "active"))
        return [row[0] for row in result.all()]

    async def _enqueue_message_batches(
        self, room_id: uuid.UUID, batch_size: int, budget: int
    ) -> int:
        """Chunk unbatched messages into consecutive jobs of batch_size.

        A trailing partial chunk is only enqueued once it has aged past
        ai_embedding_batch_flush_hours (and has a few messages), so live chat
        accumulates into full batches instead of fragmenting.
        """
        if budget <= 0:
            return 0
        last_end = await self.job_repository.max_batched_message_end_id(room_id)

        query = (
            select(Message.id, Message.created_at)
            .where(
                Message.room_id == room_id,
                Message.is_deleted == False,  # noqa: E712
            )
            .order_by(Message.id.asc())
            .limit(batch_size * max(1, min(budget, 20)))
        )
        if last_end is not None:
            query = query.where(Message.id > last_end)
        result = await self.db.execute(query)
        rows = result.all()
        if not rows:
            return 0

        flush_cutoff = datetime.utcnow() - timedelta(
            hours=self.settings.ai_embedding_batch_flush_hours
        )
        enqueued = 0
        for i in range(0, len(rows), batch_size):
            chunk = rows[i:i + batch_size]
            is_partial = len(chunk) < batch_size
            if is_partial:
                oldest_created_at = chunk[0][1]
                if oldest_created_at is not None and oldest_created_at.tzinfo is not None:
                    oldest_created_at = oldest_created_at.replace(tzinfo=None)
                if len(chunk) < MIN_TAIL_BATCH_SIZE or (
                    oldest_created_at and oldest_created_at > flush_cutoff
                ):
                    break  # leave the tail for a later sweep
            start_id, end_id = chunk[0][0], chunk[-1][0]
            created = await self.job_repository.create_pending_job(
                source_type=SOURCE_MESSAGE_BATCH,
                source_id=batch_source_id(room_id, start_id, end_id),
                room_id=room_id,
                payload={"message_start_id": start_id, "message_end_id": end_id},
            )
            if created:
                enqueued += 1
            if enqueued >= budget:
                break
        return enqueued

    # ── Job processing ────────────────────────────────────────────────────────

    async def claim_pending_jobs(
        self,
        *,
        limit: int,
        room_id: uuid.UUID | None = None,
        source_types: tuple[str, ...] | None = None,
    ) -> list[ChatEmbeddingJob]:
        await self.job_repository.mark_exhausted_pending_jobs(max_retries=self.max_retries)
        return await self.job_repository.claim_pending_jobs(
            limit=limit,
            max_retries=self.max_retries,
            room_id=room_id,
            source_types=source_types,
        )

    async def process_job(self, job: ChatEmbeddingJob) -> bool:
        """Embed one job's source text. Returns True on success."""
        try:
            built = await self._build_source_text(job)
        except Exception as exc:
            await self.job_repository.mark_failed(
                job, f"source hydration failed: {exc}", max_retries=self.max_retries, retryable=False
            )
            return False

        if built is None:
            await self.job_repository.mark_failed(
                job, "source row missing or empty", max_retries=self.max_retries, retryable=False
            )
            return False
        source_text, room_id, msg_start, msg_end = built

        try:
            vectors, tokens_in = await self.provider.embed_texts([source_text], self.model_name)
        except Exception as exc:
            await self.job_repository.mark_failed(
                job, f"embedding call failed: {exc}", max_retries=self.max_retries, retryable=True
            )
            return False

        await self.embedding_repository.upsert_embedding(
            source_type=job.source_type,
            source_id=job.source_id,
            model_name=self.model_name,
            model_version=self.model_version,
            embedding=vectors[0],
            room_id=room_id,
            message_start_id=msg_start,
            message_end_id=msg_end,
            content_preview=source_text[:CONTENT_PREVIEW_CHARS],
        )
        await self.job_repository.mark_completed(job)
        await self._log_embedding_usage(tokens_in, command="embedding_worker")
        return True

    async def _build_source_text(
        self, job: ChatEmbeddingJob
    ) -> tuple[str, uuid.UUID | None, int | None, int | None] | None:
        """Hydrate the text to embed. Returns (text, room_id, msg_start, msg_end) or None."""
        if job.source_type == SOURCE_MESSAGE_BATCH:
            from app.domains.messages.repository import MessageRepository

            payload = job.payload or {}
            start_id = payload.get("message_start_id")
            end_id = payload.get("message_end_id")
            if start_id is None or end_id is None:
                return None
            rows = await MessageRepository(self.db).get_messages_in_id_range(
                start_id, end_id, room_id=job.room_id
            )
            lines = []
            for row in rows:
                msg, user, linked_user = row[0], row[1], row[2]
                if msg.is_deleted or not (msg.content or "").strip():
                    continue
                effective = linked_user if getattr(msg, "is_imported", False) and linked_user else user
                nick = effective.nickname if effective else "?"
                ts = msg.created_at.strftime("%d %b %H:%M") if msg.created_at else "?"
                lines.append(f"[{ts}] {nick}: {msg.content.strip()}")
            if not lines:
                return None
            return "\n".join(lines), job.room_id, start_id, end_id

        if job.source_type in (SOURCE_MEMORY, SOURCE_SUMMARY):
            entry = await self.db.get(AIMemoryEntry, uuid.UUID(job.source_id))
            if entry is None or not (entry.content or "").strip():
                return None
            title = entry.title or ""
            source_text = f"{entry.memory_type}: {title}\n{entry.content}".strip()
            return source_text, entry.room_id, entry.message_start_id, entry.message_end_id

        if job.source_type == SOURCE_HUB_ITEM:
            item = await self.db.get(HubItem, uuid.UUID(job.source_id))
            if item is None:
                return None
            body = item.body or ""
            source_text = f"{item.item_type} {item.short_id}: {item.title}\n{body}".strip()
            return source_text, item.room_id, None, None

        return None

    # ── Query embedding (retrieval path) ──────────────────────────────────────

    async def embed_query(self, query_text: str) -> list[float]:
        vectors, tokens_in = await self.provider.embed_texts([query_text], self.model_name)
        await self._log_embedding_usage(tokens_in, command="search")
        return vectors[0]

    async def _log_embedding_usage(self, tokens_in: int, *, command: str) -> None:
        """Best-effort ai_usage_log row; never fails the caller."""
        try:
            await self.db.execute(
                text(
                    "INSERT INTO ai_usage_log "
                    "(provider, model, feature, tokens_in, tokens_out, cost_cents, command) "
                    "VALUES (:provider, :model, 'embedding', :tokens_in, 0, 0, :command)"
                ),
                {
                    "provider": self.settings.ai_embedding_provider,
                    "model": self.model_name,
                    "tokens_in": tokens_in,
                    "command": command,
                },
            )
        except Exception:
            logger.warning("Failed to log embedding usage", exc_info=True)

    async def status_counts(self) -> dict[str, int]:
        return await self.job_repository.status_counts()
