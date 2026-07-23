"""Topic detection read API."""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.rooms.dependencies import require_room_member
from app.domains.topic_detection.repository import TopicDetectionRepository
from app.domains.topic_detection.service import TopicDetectionService
from app.models.database import get_db_session
from app.models.room import Room

router = APIRouter(prefix="/api/v1/topics", tags=["topics"])


@router.get("/status")
async def topic_status(
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    return await TopicDetectionService(db).status(room_id=room.id)


@router.get("")
async def list_topics(
    limit: int = 20,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    detection_version: str | None = None,
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    selected_version = detection_version or get_settings().ai_topic_detection_version
    topics = await TopicDetectionRepository(db).list_topics(
        room_id=room.id,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
        detection_version=selected_version,
    )
    payloads = []
    repo = TopicDetectionRepository(db)
    for topic in topics:
        participants = await _list_participants(repo, topic_id=topic.id, room_id=room.id)
        payloads.append(_topic_payload(topic, participants=participants, include_participants=False))
    return {
        "topics": payloads,
        "limit": max(1, min(limit, 100)),
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "detection_version": selected_version,
    }


@router.get("/timeline")
async def topic_timeline(
    date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 500,
    detection_version: str | None = None,
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    repo = TopicDetectionRepository(db)
    selected_version = detection_version or get_settings().ai_topic_detection_version
    if date is not None:
        if date_from is not None or date_to is not None:
            raise HTTPException(status_code=400, detail="Use either date or date_from/date_to, not both")
        day_start, day_end = _day_bounds(date)
        topics = await repo.list_timeline_topics(
            room_id=room.id,
            day_start=day_start,
            day_end=day_end,
            detection_version=selected_version,
        )
        payloads = []
        for topic in topics:
            segments = await repo.list_segments(topic_id=topic.id, room_id=room.id)
            participants = await _list_participants(repo, topic_id=topic.id, room_id=room.id)
            payloads.append(_timeline_topic_payload(topic, segments, participants))
        return {
            "date": date.isoformat(),
            "detection_version": selected_version,
            "topics": payloads,
        }

    if date_from is None and date_to is None:
        raise HTTPException(status_code=400, detail="Pass date or date_from/date_to")
    range_start_date = date_from or date_to
    range_end_date = date_to or date_from
    if range_start_date is None or range_end_date is None:
        raise HTTPException(status_code=400, detail="Invalid date range")
    if range_end_date < range_start_date:
        raise HTTPException(status_code=400, detail="date_to must be on or after date_from")
    range_start, _ = _day_bounds(range_start_date)
    _, range_end = _day_bounds(range_end_date)
    topics = await repo.list_timeline_topics(
        room_id=room.id,
        day_start=range_start,
        day_end=range_end,
        limit=limit,
        detection_version=selected_version,
    )
    days = {
        day.isoformat(): []
        for day in _date_range(range_start_date, range_end_date)
    }
    for topic in topics:
        segments = await repo.list_segments(topic_id=topic.id, room_id=room.id)
        participants = await _list_participants(repo, topic_id=topic.id, room_id=room.id)
        topic_date = _topic_group_date(topic)
        if topic_date in days:
            days[topic_date].append(_timeline_topic_payload(topic, segments, participants))
    return {
        "date_from": range_start_date.isoformat(),
        "date_to": range_end_date.isoformat(),
        "detection_version": selected_version,
        "days": [
            {"date": day, "topics": topics}
            for day, topics in days.items()
        ],
    }


@router.get("/debug")
async def debug_topics(
    date: date | None = None,
    limit: int = 20,
    detection_version: str | None = None,
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    repo = TopicDetectionRepository(db)
    selected_version = detection_version or get_settings().ai_topic_detection_version
    if date is not None:
        day_start, day_end = _day_bounds(date)
        topics = await repo.list_timeline_topics(
            room_id=room.id,
            day_start=day_start,
            day_end=day_end,
            limit=limit,
            detection_version=selected_version,
        )
    else:
        topics = await repo.list_topics(
            room_id=room.id,
            limit=limit,
            detection_version=selected_version,
        )

    payloads = []
    for topic in topics:
        segments = await repo.list_segments(topic_id=topic.id, room_id=room.id)
        participants = await _list_participants(repo, topic_id=topic.id, room_id=room.id)
        topic_payload = _topic_payload(topic, participants=participants, include_participants=True)
        topic_payload["message_count"] = _segment_message_count(segments)
        topic_payload["segment_count"] = len(segments)
        topic_payload["segments"] = [_segment_payload(segment) for segment in segments]
        payloads.append(topic_payload)
    return {
        "date": date.isoformat() if date else None,
        "detection_version": selected_version,
        "topics": payloads,
    }


@router.get("/{topic_id}")
async def get_topic(
    topic_id: uuid.UUID,
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    repo = TopicDetectionRepository(db)
    topic = await repo.get_topic(topic_id=topic_id, room_id=room.id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    segments = await repo.list_segments(topic_id=topic.id, room_id=room.id)
    participants = await _list_participants(repo, topic_id=topic.id, room_id=room.id)
    payload = _topic_payload(topic, participants=participants, include_participants=True)
    payload["message_count"] = _segment_message_count(segments)
    payload["segment_count"] = len(segments)
    payload["segments"] = [_segment_payload(segment) for segment in segments]
    return payload


def _day_bounds(value: date) -> tuple[datetime, datetime]:
    start = datetime.combine(value, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _topic_group_date(topic) -> str:
    if topic.topic_date:
        return topic.topic_date.isoformat()
    value = topic.first_message_at or topic.bucket_start_at
    if value:
        return value.date().isoformat()
    return ""


def _dt(value) -> str | None:
    return value.isoformat() if value else None


async def _list_participants(repo, *, topic_id: uuid.UUID, room_id: uuid.UUID) -> list:
    if not hasattr(repo, "list_participants"):
        return []
    return await repo.list_participants(topic_id=topic_id, room_id=room_id)


def _topic_payload(topic, *, participants: list | None = None, include_participants: bool = False) -> dict:
    display_label = topic.refined_label or topic.label
    participants = participants or []
    payload = {
        "id": str(topic.id),
        "room_id": str(topic.room_id),
        "label": topic.label,
        "raw_label": topic.raw_label or topic.label,
        "refined_label": topic.refined_label,
        "display_label": display_label,
        "keywords": topic.keywords or [],
        "description": topic.description,
        "summary": topic.summary,
        "tags": topic.tags or [],
        "topic_type": topic.topic_type,
        "refinement_model": topic.refinement_model,
        "refined_at": _dt(topic.refined_at),
        "confidence": topic.confidence,
        "label_source": topic.label_source,
        "generation_type": topic.generation_type,
        "topic_date": topic.topic_date.isoformat() if topic.topic_date else None,
        "bucket_start_at": _dt(topic.bucket_start_at),
        "bucket_end_at": _dt(topic.bucket_end_at),
        "message_start_id": topic.message_start_id,
        "message_end_id": topic.message_end_id,
        "first_message_at": _dt(topic.first_message_at),
        "last_message_at": _dt(topic.last_message_at),
        "batch_count": topic.batch_count,
        "model_name": topic.model_name,
        "model_version": topic.model_version,
        "detection_version": topic.detection_version,
        "status": topic.status,
        "created_at": _dt(topic.created_at),
        "updated_at": _dt(topic.updated_at),
        "participant_count": len(participants),
        "participant_names": _participant_names(participants),
    }
    if include_participants:
        payload["participants"] = [_participant_payload(participant) for participant in participants]
    return payload


def _timeline_topic_payload(topic, segments, participants: list | None = None) -> dict:
    display_label = topic.refined_label or topic.label
    participants = participants or []
    return {
        "id": str(topic.id),
        "label": display_label,
        "raw_label": topic.raw_label or topic.label,
        "refined_label": topic.refined_label,
        "display_label": display_label,
        "description": topic.description,
        "summary": topic.summary,
        "tags": topic.tags or [],
        "topic_type": topic.topic_type,
        "label_source": topic.label_source,
        "refinement_model": topic.refinement_model,
        "refined_at": _dt(topic.refined_at),
        "first_message_at": _dt(topic.first_message_at),
        "last_message_at": _dt(topic.last_message_at),
        "started_at": _dt(topic.first_message_at),
        "ended_at": _dt(topic.last_message_at),
        "message_count": _segment_message_count(segments),
        "confidence": topic.confidence,
        "segments": len(segments),
        "segment_count": len(segments),
        "message_start_id": topic.message_start_id,
        "message_end_id": topic.message_end_id,
        "chat_anchor": _topic_chat_anchor(topic, segments),
        "participant_count": len(participants),
        "participant_names": _participant_names(participants),
    }


def _participant_payload(participant) -> dict:
    return {
        "id": str(participant.id) if getattr(participant, "id", None) is not None else None,
        "topic_id": str(participant.topic_id) if getattr(participant, "topic_id", None) is not None else None,
        "room_id": str(participant.room_id) if getattr(participant, "room_id", None) is not None else None,
        "user_id": str(participant.user_id) if getattr(participant, "user_id", None) is not None else None,
        "canonical_name": participant.canonical_name,
        "display_name": participant.display_name,
        "message_count": participant.message_count,
        "segment_count": participant.segment_count,
        "first_seen_at": _dt(participant.first_seen_at),
        "last_seen_at": _dt(participant.last_seen_at),
    }


def _participant_names(participants) -> list[str]:
    return [
        participant.canonical_name
        for participant in sorted(
            participants,
            key=lambda participant: (-int(getattr(participant, "message_count", 0) or 0), participant.canonical_name.lower()),
        )
    ]


def _segment_payload(segment) -> dict:
    return {
        "id": segment.id,
        "topic_id": str(segment.topic_id),
        "room_id": str(segment.room_id),
        "embedding_source_id": segment.embedding_source_id,
        "message_start_id": segment.message_start_id,
        "message_end_id": segment.message_end_id,
        "score": segment.score,
        "excerpt": segment.excerpt,
        "started_at": _dt(segment.started_at),
        "ended_at": _dt(segment.ended_at),
        "chat_anchor": _chat_anchor(segment.message_start_id),
    }


def _chat_anchor(message_id: int | None) -> str | None:
    return f"/chat?message={message_id}" if message_id is not None else None


def _topic_chat_anchor(topic, segments) -> str | None:
    message_id = topic.message_start_id
    highlight_ids = []
    for segment in segments:
        if segment.message_start_id is None:
            continue
        if message_id is None:
            message_id = segment.message_start_id
        if segment.message_start_id not in highlight_ids:
            highlight_ids.append(segment.message_start_id)
    if message_id is None:
        return None
    if not highlight_ids:
        return _chat_anchor(message_id)
    return f"/chat?message={message_id}&highlight={','.join(str(item) for item in highlight_ids)}"


def _segment_message_count(segments) -> int:
    total = 0
    for segment in segments:
        if segment.message_start_id is None or segment.message_end_id is None:
            continue
        total += max(0, segment.message_end_id - segment.message_start_id + 1)
    return total
