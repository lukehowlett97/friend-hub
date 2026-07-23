"""Shared retrieval for semantic and date-aware search.

Two retrieval modes, both bounded and room-scoped:

- retrieve_semantic: pgvector top-k over chat_embeddings (message batches,
  memories, summaries, hub items), hydrated from live rows at query time.
- retrieve_for_day: ground-truth assembly of one UTC day — messages,
  summaries/memories, hub items, photos, polls/events/reminders. Needs no
  embeddings, so date questions work even with the feature flag off.

Results are RetrievedSource records with display anchors (/chat?message=ID,
#E-1 short ids) so replies can always link back to their sources.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.ai.repository import AIMemoryRepository
from app.domains.chat_embeddings.repository import (
    SOURCE_HUB_ITEM,
    SOURCE_MEMORY,
    SOURCE_MESSAGE_BATCH,
    SOURCE_SUMMARY,
    ChatEmbeddingRepository,
    VectorSearchUnavailableError,
)
from app.models.event import Event
from app.models.hub_item import HubItem
from app.models.message import Message
from app.models.photo import Photo
from app.models.planning import Poll, PollStatus, Reminder

logger = logging.getLogger(__name__)

DAY_SECTION_LIMIT = 5  # per item type in retrieve_for_day


@dataclass
class RetrievedSource:
    kind: str            # message_batch | summary | memory | hub_item | photo | poll | event | reminder
    title: str
    text: str            # prompt-ready content, hydrated from live rows
    anchor: Optional[str]  # "/chat?message=123" | "#E-1" | None
    when: str            # "1 Jun 2025"
    score: Optional[float] = None
    message_start_id: Optional[int] = None
    message_end_id: Optional[int] = None


async def short_ref(db: AsyncSession, room_id, source_type: str, source_id: int) -> str:
    """Resolve the #short-id reference for a hub-item-backed entity."""
    result = await db.execute(
        select(HubItem.short_id).where(
            HubItem.room_id == room_id,
            HubItem.source_type == source_type,
            HubItem.source_id == source_id,
        )
    )
    sid = result.scalar_one_or_none()
    return f"#{sid}" if sid else ""


def _when(dt: Optional[datetime]) -> str:
    return f"{dt.day} {dt:%b %Y}" if dt else ""


class ChatRetrievalService:
    def __init__(self, db: AsyncSession, *, settings=None, embed_service=None):
        self.db = db
        self.settings = settings or get_settings()
        self._embed_service = embed_service
        self.embedding_repo = ChatEmbeddingRepository(db)
        self.memory_repo = AIMemoryRepository(db)

    @property
    def embed_service(self):
        if self._embed_service is None:
            from app.domains.chat_embeddings.service import ChatEmbeddingJobService

            self._embed_service = ChatEmbeddingJobService(self.db)
        return self._embed_service

    async def has_embeddings(self, room_id: Optional[uuid.UUID]) -> bool:
        """Whether semantic retrieval can serve this room right now."""
        if not self.settings.ai_enable_chat_embeddings:
            return False
        try:
            return await self.embedding_repo.has_any(
                room_id=room_id,
                model_name=self.settings.ai_embedding_model,
                model_version=self.settings.ai_embedding_provider,
            )
        except Exception:
            logger.warning("has_embeddings check failed", exc_info=True)
            return False

    # ── Semantic retrieval ────────────────────────────────────────────────────

    async def retrieve_semantic(
        self,
        query: str,
        room_id: Optional[uuid.UUID],
        *,
        k: int = 8,
        source_types: Optional[tuple] = None,
        date_window: Optional[tuple] = None,
        message_id_window: Optional[tuple] = None,
    ) -> list[RetrievedSource]:
        """Cosine top-k, hydrated. Returns [] on any failure so callers fall back."""
        k = min(k, self.settings.ai_retrieval_top_k)
        try:
            query_embedding = await self.embed_service.embed_query(query)
            hits = await self.embedding_repo.search_similar(
                query_embedding=query_embedding,
                model_name=self.settings.ai_embedding_model,
                model_version=self.settings.ai_embedding_provider,
                room_id=room_id,
                source_types=source_types,
                limit=k,
                similarity_floor=self.settings.ai_retrieval_similarity_floor,
                message_id_window=message_id_window,
                date_window=date_window,
            )
        except VectorSearchUnavailableError:
            logger.info("Vector search unavailable; caller should fall back to keyword search")
            return []
        except Exception:
            logger.warning("Semantic retrieval failed; falling back", exc_info=True)
            return []

        sources: list[RetrievedSource] = []
        for hit in hits:
            try:
                hydrated = await self._hydrate(hit)
            except Exception:
                logger.warning("Failed to hydrate %s:%s", hit.source_type, hit.source_id, exc_info=True)
                continue
            if hydrated:
                sources.append(hydrated)

        # Observability: score distribution per query lets us judge the floor.
        scores = [f"{h.score:.3f}" for h in hits[:5]]
        logger.info(
            "semantic retrieval: query=%r hits=%d hydrated=%d top_scores=[%s] floor=%.2f",
            query[:80], len(hits), len(sources), ", ".join(scores),
            self.settings.ai_retrieval_similarity_floor,
        )
        return sources

    async def _hydrate(self, hit) -> Optional[RetrievedSource]:
        if hit.source_type == SOURCE_MESSAGE_BATCH:
            from app.domains.messages.repository import MessageRepository

            if hit.message_start_id is None or hit.message_end_id is None:
                return None
            rows = await MessageRepository(self.db).get_messages_in_id_range(
                hit.message_start_id, hit.message_end_id, room_id=hit.room_id
            )
            lines = []
            first_ts = None
            for row in rows:
                msg, user, linked_user = row[0], row[1], row[2]
                if msg.is_deleted or not (msg.content or "").strip():
                    continue
                if first_ts is None:
                    first_ts = msg.created_at
                effective = linked_user if getattr(msg, "is_imported", False) and linked_user else user
                nick = effective.nickname if effective else "?"
                ts = msg.created_at.strftime("%d %b %H:%M") if msg.created_at else "?"
                lines.append(f"[{ts}] {nick}: {msg.content.strip()}")
            if not lines:
                return None
            return RetrievedSource(
                kind=SOURCE_MESSAGE_BATCH,
                title=f"Chat excerpt ({_when(first_ts)})",
                text="\n".join(lines),
                anchor=f"/chat?message={hit.message_start_id}",
                when=_when(first_ts),
                score=hit.score,
                message_start_id=hit.message_start_id,
                message_end_id=hit.message_end_id,
            )

        if hit.source_type in (SOURCE_MEMORY, SOURCE_SUMMARY):
            entries = await self.memory_repo.list_by_ids([hit.source_id])
            if not entries:
                return None
            entry = entries[0]
            anchor = (
                f"/chat?message={entry.message_start_id}"
                if entry.message_start_id is not None
                else None
            )
            return RetrievedSource(
                kind=hit.source_type,
                title=entry.title or entry.memory_type,
                text=f"{entry.memory_type}: {entry.content}",
                anchor=anchor,
                when=_when(entry.created_at),
                score=hit.score,
                message_start_id=entry.message_start_id,
                message_end_id=entry.message_end_id,
            )

        if hit.source_type == SOURCE_HUB_ITEM:
            item = await self.db.get(HubItem, uuid.UUID(hit.source_id))
            if item is None:
                return None
            return RetrievedSource(
                kind=SOURCE_HUB_ITEM,
                title=f"{item.item_type} #{item.short_id}: {item.title}",
                text=(item.body or item.title or "").strip(),
                anchor=f"#{item.short_id}",
                when=_when(item.created_at),
                score=hit.score,
            )

        return None

    # ── Date-window retrieval (no embeddings required) ───────────────────────

    async def retrieve_for_day(
        self,
        room_id: Optional[uuid.UUID],
        day_start: datetime,
        day_end: datetime,
        *,
        max_messages: int = 60,
    ) -> list[RetrievedSource]:
        sources: list[RetrievedSource] = []
        when = _when(day_start)

        # Day message stats + raw excerpt (bounded — never the unfiltered day)
        stats = await self.db.execute(
            select(func.min(Message.id), func.max(Message.id), func.count(Message.id)).where(
                Message.room_id == room_id,
                Message.created_at >= day_start,
                Message.created_at < day_end,
                Message.is_deleted == False,  # noqa: E712
            )
        )
        min_id, max_id, msg_count = stats.one()

        # Stored summaries/memories covering the day come first: best signal per token
        if room_id is not None:
            entries = await self.memory_repo.list_entries_for_window(
                room_id, day_start, day_end,
                message_min_id=min_id, message_max_id=max_id,
            )
            for entry in entries:
                anchor = (
                    f"/chat?message={entry.message_start_id}"
                    if entry.message_start_id is not None
                    else None
                )
                kind = SOURCE_SUMMARY if entry.memory_type in ("daily_summary", "weekly_summary") else SOURCE_MEMORY
                sources.append(RetrievedSource(
                    kind=kind,
                    title=entry.title or entry.memory_type,
                    text=f"{entry.memory_type}: {entry.content}",
                    anchor=anchor,
                    when=_when(entry.created_at),
                    message_start_id=entry.message_start_id,
                    message_end_id=entry.message_end_id,
                ))

        if min_id is not None:
            from app.domains.messages.repository import MessageRepository

            rows = await MessageRepository(self.db).get_messages_in_id_range(
                min_id, max_id, room_id=room_id, limit=max_messages
            )
            lines = []
            for row in rows:
                msg, user, linked_user = row[0], row[1], row[2]
                if msg.is_deleted or not (msg.content or "").strip():
                    continue
                effective = linked_user if getattr(msg, "is_imported", False) and linked_user else user
                nick = effective.nickname if effective else "?"
                ts = msg.created_at.strftime("%H:%M") if msg.created_at else "?"
                lines.append(f"[{ts}] {nick}: {msg.content.strip()}")
            if lines:
                truncated = msg_count > len(lines)
                note = f" (first {len(lines)} of {msg_count} messages)" if truncated else ""
                sources.append(RetrievedSource(
                    kind=SOURCE_MESSAGE_BATCH,
                    title=f"Chat on {when}{note}",
                    text="\n".join(lines),
                    anchor=f"/chat?message={min_id}",
                    when=when,
                    message_start_id=min_id,
                    message_end_id=max_id,
                ))

        sources.extend(await self._day_hub_items(room_id, day_start, day_end, when))
        sources.extend(await self._day_photos(room_id, day_start, day_end, when))
        sources.extend(await self._day_planning_items(room_id, day_start, day_end, when))
        return sources

    async def _day_hub_items(self, room_id, day_start, day_end, when) -> list[RetrievedSource]:
        result = await self.db.execute(
            select(HubItem)
            .where(
                HubItem.room_id == room_id,
                HubItem.created_at >= day_start,
                HubItem.created_at < day_end,
            )
            .order_by(HubItem.created_at)
            .limit(DAY_SECTION_LIMIT)
        )
        return [
            RetrievedSource(
                kind=SOURCE_HUB_ITEM,
                title=f"{item.item_type} #{item.short_id}: {item.title}",
                text=(item.body or item.title or "").strip(),
                anchor=f"#{item.short_id}",
                when=when,
            )
            for item in result.scalars().all()
        ]

    async def _day_photos(self, room_id, day_start, day_end, when) -> list[RetrievedSource]:
        taken_in_window = (Photo.taken_at >= day_start) & (Photo.taken_at < day_end)
        uploaded_in_window = (
            Photo.taken_at.is_(None)
            & (Photo.created_at >= day_start)
            & (Photo.created_at < day_end)
        )
        result = await self.db.execute(
            select(func.count(Photo.id)).where(
                Photo.room_id == room_id,
                or_(taken_in_window, uploaded_in_window),
            )
        )
        count = int(result.scalar() or 0)
        if count == 0:
            return []
        return [RetrievedSource(
            kind="photo",
            title=f"{count} photo{'s' if count != 1 else ''} from {when}",
            text=f"{count} photo{'s' if count != 1 else ''} were taken or shared on {when}.",
            anchor="/photos",
            when=when,
        )]

    async def _day_planning_items(self, room_id, day_start, day_end, when) -> list[RetrievedSource]:
        sources: list[RetrievedSource] = []

        polls = await self.db.execute(
            select(Poll)
            .where(Poll.room_id == room_id, Poll.created_at >= day_start, Poll.created_at < day_end)
            .order_by(Poll.created_at)
            .limit(DAY_SECTION_LIMIT)
        )
        for poll in polls.scalars().all():
            ref = await short_ref(self.db, room_id, "poll", poll.id)
            status = poll.status or PollStatus.live.value
            sources.append(RetrievedSource(
                kind="poll",
                title=f"Poll {ref} created".strip(),
                text=f'Poll {ref} "{poll.question}" was created ({status}).',
                anchor=ref or None,
                when=when,
            ))

        events = await self.db.execute(
            select(Event)
            .where(
                Event.room_id == room_id,
                or_(
                    (Event.created_at >= day_start) & (Event.created_at < day_end),
                    (Event.starts_at >= day_start) & (Event.starts_at < day_end),
                ),
            )
            .order_by(Event.created_at)
            .limit(DAY_SECTION_LIMIT)
        )
        for event in events.scalars().all():
            ref = await short_ref(self.db, room_id, "event", event.id)
            happened = event.starts_at and day_start <= event.starts_at < day_end
            verb = "happened" if happened else "was created"
            starts = f" (starts {event.starts_at:%d %b %H:%M})" if event.starts_at else ""
            sources.append(RetrievedSource(
                kind="event",
                title=f"Event {ref} {verb}".strip(),
                text=f'Event {ref} "{event.title}"{starts} {verb} on {when}.',
                anchor=ref or None,
                when=when,
            ))

        reminders = await self.db.execute(
            select(Reminder)
            .where(Reminder.room_id == room_id, Reminder.created_at >= day_start, Reminder.created_at < day_end)
            .order_by(Reminder.created_at)
            .limit(DAY_SECTION_LIMIT)
        )
        for reminder in reminders.scalars().all():
            ref = await short_ref(self.db, room_id, "reminder", reminder.id)
            sources.append(RetrievedSource(
                kind="reminder",
                title=f"Reminder {ref} created".strip(),
                text=f'Reminder {ref} "{reminder.text}" was created.',
                anchor=ref or None,
                when=when,
            ))

        return sources
