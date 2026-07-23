from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import and_, delete, desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.chat_topic import (
    ChatTopic,
    ChatTopicParticipant,
    ChatTopicSegment,
    RoomParticipantAlias,
    RoomTopicDetectionSettings,
)
from app.models.message import User
from app.models.room import RoomMembership

GENERATION_TYPE_SEMANTIC_CLUSTER = "semantic_time_cluster"
LABEL_SOURCE_KEYWORD_PLACEHOLDER = "keyword_placeholder"
TOPIC_STATUS_ACTIVE = "active"


@dataclass(frozen=True)
class TopicEmbeddingBatch:
    source_id: str
    room_id: uuid.UUID
    message_start_id: int
    message_end_id: int
    embedding: list[float]
    content_preview: str | None
    first_message_at: datetime | None
    last_message_at: datetime | None


@dataclass(frozen=True)
class TopicDraftSegment:
    embedding_source_id: str
    message_start_id: int
    message_end_id: int
    score: float
    excerpt: str | None
    started_at: datetime | None
    ended_at: datetime | None


@dataclass(frozen=True)
class TopicDraft:
    label: str
    keywords: list[str]
    description: str | None
    confidence: float
    topic_date: date | None
    bucket_start_at: datetime | None
    bucket_end_at: datetime | None
    message_start_id: int | None
    message_end_id: int | None
    first_message_at: datetime | None
    last_message_at: datetime | None
    batch_count: int
    segments: list[TopicDraftSegment]


@dataclass
class TopicParticipantDraft:
    user_id: uuid.UUID | None
    canonical_name: str
    display_name: str | None
    message_count: int = 0
    segment_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class TopicDetectionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_embedding_batches(
        self,
        *,
        room_id: uuid.UUID,
        model_name: str,
        model_version: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 1000,
    ) -> list[TopicEmbeddingBatch]:
        where = [
            "ce.source_type = 'message_batch'",
            "ce.room_id = :room_id",
            "ce.model_name = :model_name",
            "ce.model_version = :model_version",
            "ce.message_start_id IS NOT NULL",
            "ce.message_end_id IS NOT NULL",
            "start_msg.is_deleted = FALSE",
            "end_msg.is_deleted = FALSE",
        ]
        params: dict = {
            "room_id": str(room_id),
            "model_name": model_name,
            "model_version": model_version,
            "limit": max(1, limit),
        }
        if date_from is not None:
            where.append("end_msg.created_at >= :date_from")
            params["date_from"] = date_from
        if date_to is not None:
            where.append("start_msg.created_at < :date_to")
            params["date_to"] = date_to

        result = await self.db.execute(
            text(f"""
                SELECT
                    ce.source_id,
                    ce.room_id,
                    ce.message_start_id,
                    ce.message_end_id,
                    CAST(ce.embedding AS text) AS embedding_text,
                    ce.content_preview,
                    start_msg.created_at AS first_message_at,
                    end_msg.created_at AS last_message_at
                FROM chat_embeddings ce
                JOIN messages start_msg ON start_msg.id = ce.message_start_id
                JOIN messages end_msg ON end_msg.id = ce.message_end_id
                WHERE {' AND '.join(where)}
                ORDER BY start_msg.created_at ASC, ce.message_start_id ASC
                LIMIT :limit
            """),
            params,
        )
        batches: list[TopicEmbeddingBatch] = []
        for row in result.mappings().all():
            batches.append(
                TopicEmbeddingBatch(
                    source_id=row["source_id"],
                    room_id=row["room_id"],
                    message_start_id=row["message_start_id"],
                    message_end_id=row["message_end_id"],
                    embedding=parse_vector_text(row["embedding_text"]),
                    content_preview=row["content_preview"],
                    first_message_at=row["first_message_at"],
                    last_message_at=row["last_message_at"],
                )
            )
        return batches

    async def get_room_settings(self, *, room_id: uuid.UUID) -> RoomTopicDetectionSettings | None:
        result = await self.db.execute(
            select(RoomTopicDetectionSettings).where(RoomTopicDetectionSettings.room_id == room_id)
        )
        return result.scalar_one_or_none()

    async def upsert_room_settings(
        self,
        *,
        room_id: uuid.UUID,
        similarity_threshold: float | None = None,
        enabled: bool | None = None,
        hard_gap_minutes: int | None = None,
        soft_gap_minutes: int | None = None,
        max_topic_duration_hours: int | None = None,
    ) -> RoomTopicDetectionSettings:
        row = await self.get_room_settings(room_id=room_id)
        if row is None:
            row = RoomTopicDetectionSettings(room_id=room_id)
            self.db.add(row)
        if similarity_threshold is not None:
            row.similarity_threshold = similarity_threshold
        if enabled is not None:
            row.enabled = enabled
        if hard_gap_minutes is not None:
            row.hard_gap_minutes = hard_gap_minutes
        if soft_gap_minutes is not None:
            row.soft_gap_minutes = soft_gap_minutes
        if max_topic_duration_hours is not None:
            row.max_topic_duration_hours = max_topic_duration_hours
        await self.db.flush()
        return row

    async def list_participant_name_aliases(self, *, room_id: uuid.UUID) -> dict[str, str]:
        """Display-name -> canonical-name mappings for AI export text only."""
        aliases: dict[str, str] = {}
        result = await self.db.execute(
            select(RoomParticipantAlias.display_name, RoomParticipantAlias.canonical_name)
            .where(RoomParticipantAlias.room_id == room_id)
            .order_by(RoomParticipantAlias.display_name.asc())
        )
        for display_name, canonical_name in result.all():
            display = _clean_name(display_name)
            canonical = _canonical_name(canonical_name)
            if display and canonical:
                aliases[display] = canonical

        result = await self.db.execute(
            select(User.nickname, User.display_name, User.username)
            .join(RoomMembership, RoomMembership.user_id == User.id)
            .where(RoomMembership.room_id == room_id)
            .order_by(User.nickname.asc())
        )
        for nickname, display_name, username in result.all():
            display = _clean_name(nickname)
            if not display or display.casefold() in {key.casefold() for key in aliases}:
                continue
            canonical = _canonical_name(display_name) or _canonical_name(username) or display
            aliases[display] = canonical
        return aliases

    async def replace_generated_topics(
        self,
        *,
        room_id: uuid.UUID,
        model_name: str,
        model_version: str,
        detection_version: str,
        topics: list[TopicDraft],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        conditions = [
            ChatTopic.room_id == room_id,
            ChatTopic.model_name == model_name,
            ChatTopic.model_version == model_version,
            ChatTopic.detection_version == detection_version,
        ]
        if date_from is not None:
            conditions.append(ChatTopic.bucket_end_at >= date_from)
        if date_to is not None:
            conditions.append(ChatTopic.bucket_start_at < date_to)

        await self.db.execute(delete(ChatTopic).where(and_(*conditions)))
        inserted = 0
        aliases = await self.list_participant_name_aliases(room_id=room_id)
        for draft in topics:
            topic = ChatTopic(
                room_id=room_id,
                label=draft.label,
                raw_label=draft.label,
                keywords=draft.keywords,
                description=draft.description,
                confidence=draft.confidence,
                label_source=LABEL_SOURCE_KEYWORD_PLACEHOLDER,
                generation_type=GENERATION_TYPE_SEMANTIC_CLUSTER,
                topic_date=draft.topic_date,
                bucket_start_at=draft.bucket_start_at,
                bucket_end_at=draft.bucket_end_at,
                message_start_id=draft.message_start_id,
                message_end_id=draft.message_end_id,
                first_message_at=draft.first_message_at,
                last_message_at=draft.last_message_at,
                batch_count=draft.batch_count,
                model_name=model_name,
                model_version=model_version,
                detection_version=detection_version,
                status=TOPIC_STATUS_ACTIVE,
            )
            self.db.add(topic)
            await self.db.flush()
            for segment in draft.segments:
                self.db.add(
                    ChatTopicSegment(
                        topic_id=topic.id,
                        room_id=room_id,
                        embedding_source_id=segment.embedding_source_id,
                        message_start_id=segment.message_start_id,
                        message_end_id=segment.message_end_id,
                        score=segment.score,
                        excerpt=segment.excerpt,
                        started_at=segment.started_at,
                        ended_at=segment.ended_at,
                    )
                )
            for participant in await self._participant_drafts_for_topic(
                room_id=room_id,
                segments=draft.segments,
                aliases=aliases,
            ):
                self.db.add(
                    ChatTopicParticipant(
                        topic_id=topic.id,
                        room_id=room_id,
                        user_id=participant.user_id,
                        canonical_name=participant.canonical_name,
                        display_name=participant.display_name,
                        message_count=participant.message_count,
                        segment_count=participant.segment_count,
                        first_seen_at=participant.first_seen_at,
                        last_seen_at=participant.last_seen_at,
                    )
                )
            inserted += 1
        await self.db.flush()
        return inserted

    async def count_current_topics(
        self,
        *,
        room_id: uuid.UUID,
        model_name: str,
        model_version: str,
        detection_version: str,
    ) -> int:
        result = await self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM chat_topics
                WHERE room_id = :room_id
                  AND model_name = :model_name
                  AND model_version = :model_version
                  AND detection_version = :detection_version
                  AND generation_type = :generation_type
                  AND status = 'active'
                """
            ),
            {
                "room_id": str(room_id),
                "model_name": model_name,
                "model_version": model_version,
                "detection_version": detection_version,
                "generation_type": GENERATION_TYPE_SEMANTIC_CLUSTER,
            },
        )
        return int(result.scalar() or 0)

    async def list_topics(
        self,
        *,
        room_id: uuid.UUID,
        limit: int = 20,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        detection_version: str | None = None,
    ) -> list[ChatTopic]:
        query = (
            select(ChatTopic)
            .where(ChatTopic.room_id == room_id, ChatTopic.status == TOPIC_STATUS_ACTIVE)
            .order_by(desc(ChatTopic.bucket_start_at), desc(ChatTopic.created_at))
            .limit(max(1, min(limit, 100)))
        )
        if detection_version is not None:
            query = query.where(ChatTopic.detection_version == detection_version)
        if date_from is not None:
            query = query.where(ChatTopic.bucket_end_at >= date_from)
        if date_to is not None:
            query = query.where(ChatTopic.bucket_start_at < date_to)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_timeline_topics(
        self,
        *,
        room_id: uuid.UUID,
        day_start: datetime,
        day_end: datetime,
        limit: int = 100,
        detection_version: str | None = None,
    ) -> list[ChatTopic]:
        """Topics whose bucket overlaps one calendar day, ordered for a timeline."""
        query = (
            select(ChatTopic)
            .where(
                ChatTopic.room_id == room_id,
                ChatTopic.status == TOPIC_STATUS_ACTIVE,
                ChatTopic.bucket_end_at >= day_start,
                ChatTopic.bucket_start_at < day_end,
            )
            .order_by(ChatTopic.bucket_start_at.asc(), ChatTopic.created_at.asc())
            .limit(max(1, min(limit, 200)))
        )
        if detection_version is not None:
            query = query.where(ChatTopic.detection_version == detection_version)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_topics_for_refinement(
        self,
        *,
        room_id: uuid.UUID,
        day_start: datetime,
        day_end: datetime,
        detection_version: str,
        topic_id: uuid.UUID | None = None,
        force: bool = False,
        limit: int | None = None,
    ) -> list[ChatTopic]:
        conditions = [
            ChatTopic.room_id == room_id,
            ChatTopic.status == TOPIC_STATUS_ACTIVE,
            ChatTopic.detection_version == detection_version,
            ChatTopic.generation_type == GENERATION_TYPE_SEMANTIC_CLUSTER,
            ChatTopic.bucket_end_at >= day_start,
            ChatTopic.bucket_start_at < day_end,
        ]
        if topic_id is not None:
            conditions.append(ChatTopic.id == topic_id)
        if not force:
            conditions.append(ChatTopic.refined_label.is_(None))
        query = (
            select(ChatTopic)
            .options(selectinload(ChatTopic.segments), selectinload(ChatTopic.participants))
            .where(*conditions)
            .order_by(ChatTopic.bucket_start_at.asc(), ChatTopic.created_at.asc())
        )
        if limit is not None:
            query = query.limit(max(1, limit))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_topics_for_refinement_export(
        self,
        *,
        room_id: uuid.UUID,
        date_from: datetime,
        date_to: datetime,
        detection_version: str,
        include_already_refined: bool = False,
        limit: int | None = None,
    ) -> list[ChatTopic]:
        conditions = [
            ChatTopic.room_id == room_id,
            ChatTopic.status == TOPIC_STATUS_ACTIVE,
            ChatTopic.detection_version == detection_version,
            ChatTopic.generation_type == GENERATION_TYPE_SEMANTIC_CLUSTER,
            ChatTopic.bucket_end_at >= date_from,
            ChatTopic.bucket_start_at < date_to,
        ]
        if not include_already_refined:
            conditions.append(ChatTopic.refined_label.is_(None))
        query = (
            select(ChatTopic)
            .options(selectinload(ChatTopic.segments), selectinload(ChatTopic.participants))
            .where(*conditions)
            .order_by(ChatTopic.bucket_start_at.asc(), ChatTopic.created_at.asc())
        )
        if limit is not None:
            query = query.limit(max(1, limit))
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_topic_for_refinement_import(
        self,
        *,
        topic_id: uuid.UUID,
        room_id: uuid.UUID,
    ) -> ChatTopic | None:
        result = await self.db.execute(
            select(ChatTopic)
            .options(selectinload(ChatTopic.segments), selectinload(ChatTopic.participants))
            .where(
                ChatTopic.id == topic_id,
                ChatTopic.room_id == room_id,
                ChatTopic.status == TOPIC_STATUS_ACTIVE,
            )
        )
        return result.scalar_one_or_none()

    async def apply_refinement(
        self,
        *,
        topic: ChatTopic,
        title: str,
        summary: str,
        tags: list[str],
        topic_type: str,
        confidence: float,
        refinement_model: str,
    ) -> None:
        if topic.raw_label is None:
            topic.raw_label = topic.label
        topic.refined_label = title
        topic.summary = summary
        topic.tags = tags
        topic.topic_type = topic_type
        topic.confidence = confidence
        topic.label_source = "llm_refined"
        topic.refinement_model = refinement_model
        topic.refined_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def get_topic(self, *, topic_id: uuid.UUID, room_id: uuid.UUID) -> ChatTopic | None:
        result = await self.db.execute(
            select(ChatTopic)
            .where(ChatTopic.id == topic_id, ChatTopic.room_id == room_id)
        )
        return result.scalar_one_or_none()

    async def list_segments(self, *, topic_id: uuid.UUID, room_id: uuid.UUID) -> list[ChatTopicSegment]:
        result = await self.db.execute(
            select(ChatTopicSegment)
            .where(ChatTopicSegment.topic_id == topic_id, ChatTopicSegment.room_id == room_id)
            .order_by(ChatTopicSegment.started_at.asc(), ChatTopicSegment.message_start_id.asc())
        )
        return list(result.scalars().all())

    async def list_participants(self, *, topic_id: uuid.UUID, room_id: uuid.UUID) -> list[ChatTopicParticipant]:
        result = await self.db.execute(
            select(ChatTopicParticipant)
            .where(ChatTopicParticipant.topic_id == topic_id, ChatTopicParticipant.room_id == room_id)
            .order_by(ChatTopicParticipant.message_count.desc(), ChatTopicParticipant.canonical_name.asc())
        )
        return list(result.scalars().all())

    async def _participant_drafts_for_topic(
        self,
        *,
        room_id: uuid.UUID,
        segments: list[TopicDraftSegment],
        aliases: dict[str, str],
    ) -> list[TopicParticipantDraft]:
        from app.domains.messages.repository import MessageRepository

        participants: dict[str, TopicParticipantDraft] = {}
        message_repo = MessageRepository(self.db)
        for segment in segments:
            if segment.message_start_id is None or segment.message_end_id is None:
                continue
            rows = await message_repo.get_messages_in_id_range(
                segment.message_start_id,
                segment.message_end_id,
                room_id=room_id,
            )
            seen_in_segment: set[str] = set()
            for row in rows:
                message = row[0]
                user = _effective_message_user(row)
                if getattr(message, "is_deleted", False):
                    continue
                imported_display_name = _imported_sender_name(row)
                display_name = _message_display_name(
                    user=user,
                    imported_display_name=imported_display_name,
                    prefer_imported=bool(getattr(message, "is_imported", False)),
                )
                canonical_name = participant_canonical_name(
                    user=user,
                    display_name=display_name,
                    aliases=aliases,
                    prefer_display_name=bool(imported_display_name),
                )
                if not canonical_name:
                    continue
                participant = participants.get(canonical_name)
                if participant is None:
                    participant = TopicParticipantDraft(
                        user_id=getattr(user, "id", None),
                        canonical_name=canonical_name,
                        display_name=display_name,
                    )
                    participants[canonical_name] = participant
                if participant.user_id is None:
                    participant.user_id = getattr(user, "id", None)
                if participant.display_name is None:
                    participant.display_name = display_name
                participant.message_count += 1
                if canonical_name not in seen_in_segment:
                    participant.segment_count += 1
                    seen_in_segment.add(canonical_name)
                created_at = getattr(message, "created_at", None)
                if created_at is not None:
                    if participant.first_seen_at is None or created_at < participant.first_seen_at:
                        participant.first_seen_at = created_at
                    if participant.last_seen_at is None or created_at > participant.last_seen_at:
                        participant.last_seen_at = created_at
        return sorted(
            participants.values(),
            key=lambda participant: (-participant.message_count, participant.canonical_name.lower()),
        )


def parse_vector_text(value: str | list[float]) -> list[float]:
    if isinstance(value, list):
        return [float(v) for v in value]
    text_value = (value or "").strip()
    if not text_value:
        return []
    if text_value.startswith("[") and text_value.endswith("]"):
        text_value = text_value[1:-1]
    return [float(part.strip()) for part in text_value.split(",") if part.strip()]


def _clean_name(value: str | None) -> str | None:
    cleaned = " ".join(str(value or "").strip().split())
    return cleaned or None


def _canonical_name(value: str | None) -> str | None:
    cleaned = _clean_name(value)
    if not cleaned or "@" in cleaned:
        return None
    return cleaned


def _effective_message_user(row):
    message = row[0]
    user = row[1] if len(row) > 1 else None
    linked_user = row[2] if len(row) > 2 else None
    if getattr(message, "is_imported", False) and linked_user is not None:
        return linked_user
    return user


def _imported_sender_name(row) -> str | None:
    imported_identity = row[6] if len(row) > 6 else None
    return _canonical_name(getattr(imported_identity, "source_display_name", None))


def _message_display_name(*, user, imported_display_name: str | None = None, prefer_imported: bool = False) -> str | None:
    if prefer_imported and imported_display_name:
        return imported_display_name
    if user is None:
        return imported_display_name
    return (
        _clean_name(getattr(user, "nickname", None))
        or _clean_name(getattr(user, "display_name", None))
        or _clean_name(getattr(user, "username", None))
        or imported_display_name
    )


def participant_canonical_name(
    *,
    user,
    display_name: str | None,
    aliases: dict[str, str],
    prefer_display_name: bool = False,
) -> str | None:
    display = _clean_name(display_name)
    if display and display in aliases:
        return aliases[display]
    if display:
        for alias_display, canonical in aliases.items():
            if alias_display.casefold() == display.casefold():
                return canonical
    if prefer_display_name:
        return (
            _canonical_name(display)
            or _canonical_name(getattr(user, "display_name", None) if user is not None else None)
            or _canonical_name(getattr(user, "username", None) if user is not None else None)
        )
    return (
        _canonical_name(getattr(user, "display_name", None) if user is not None else None)
        or _canonical_name(getattr(user, "username", None) if user is not None else None)
        or _canonical_name(display)
    )
