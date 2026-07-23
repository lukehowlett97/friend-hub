from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.domains.topic_detection.refinement import (
    TopicRefinementService,
)
from app.domains.topic_detection.refinement_io import (
    NAME_MODES,
    NameNormalizer,
    build_manifest,
    build_refinement_job,
    load_jsonl,
    manifest_path_for,
    parse_import_record,
    parse_redaction,
    source_hash_from_topic,
)
from app.domains.topic_detection.repository import TopicDetectionRepository
from app.domains.topic_detection.service import TopicDetectionService
from app.models.chat_topic import ChatTopic
from app.models.database import async_session_factory
from app.models.room import Room

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedRoom:
    id: uuid.UUID
    slug: str
    name: str


async def run_once(
    *,
    room_id: uuid.UUID | None,
    room_slug: str | None = None,
    room_name: str | None = None,
    all_rooms: bool = False,
    limit_batches: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    dry_run: bool = False,
    similarity_threshold: float | None = None,
    hard_gap_minutes: int | None = None,
    soft_gap_minutes: int | None = None,
    max_topic_duration_hours: int | None = None,
) -> list[dict]:
    settings = get_settings()
    if not settings.ai_topic_detection_enabled:
        logger.info("Topic detection is disabled. Set AI_TOPIC_DETECTION_ENABLED=true to run it.")
        return []

    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=all_rooms,
        )
        results = []
        for room in rooms:
            logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
            service = TopicDetectionService(db)
            result = await service.generate_topics(
                room_id=room.id,
                date_from=date_from,
                date_to=date_to,
                limit_batches=limit_batches,
                dry_run=dry_run,
                similarity_threshold=similarity_threshold,
                hard_gap_minutes=hard_gap_minutes,
                soft_gap_minutes=soft_gap_minutes,
                max_topic_duration_hours=max_topic_duration_hours,
            )
            results.append(result)
            if dry_run:
                await db.rollback()
            else:
                await db.commit()
            logger.info(
                "Topic detection room=%s status=%s scanned=%s detected=%s written=%s",
                room.id,
                result["status"],
                result["batches_scanned"],
                result["topics_detected"],
                result["topics_written"],
            )
        return results


async def run_date_backfill(
    *,
    room_id: uuid.UUID | None,
    room_slug: str | None = None,
    room_name: str | None = None,
    all_rooms: bool = False,
    date_value: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit_batches: int | None = None,
    dry_run: bool = False,
    similarity_threshold: float | None = None,
    hard_gap_minutes: int | None = None,
    soft_gap_minutes: int | None = None,
    max_topic_duration_hours: int | None = None,
) -> list[dict]:
    settings = get_settings()
    if not settings.ai_topic_detection_enabled:
        logger.info("Topic detection is disabled. Set AI_TOPIC_DETECTION_ENABLED=true to run it.")
        return []

    windows = _date_windows(date_value=date_value, date_from=date_from, date_to=date_to)
    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=all_rooms,
        )
        results = []
        for window_date, day_start, day_end in windows:
            for room in rooms:
                logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
                service = TopicDetectionService(db)
                result = await service.generate_topics(
                    room_id=room.id,
                    date_from=day_start,
                    date_to=day_end,
                    limit_batches=limit_batches,
                    dry_run=dry_run,
                    similarity_threshold=similarity_threshold,
                    hard_gap_minutes=hard_gap_minutes,
                    soft_gap_minutes=soft_gap_minutes,
                    max_topic_duration_hours=max_topic_duration_hours,
                )
                result["date"] = window_date.isoformat()
                results.append(result)
                if dry_run:
                    await db.rollback()
                else:
                    await db.commit()
                logger.info(
                    "Topic detection date=%s room=%s status=%s scanned=%s detected=%s written=%s dry_run=%s",
                    window_date.isoformat(),
                    room.id,
                    result["status"],
                    result["batches_scanned"],
                    result["topics_detected"],
                    result["topics_written"],
                    dry_run,
                )
        return results


async def _resolve_room_ids(db, *, room_id: uuid.UUID | None, all_rooms: bool) -> list[uuid.UUID]:
    rooms = await _resolve_rooms(db, room_id=room_id, all_rooms=all_rooms)
    return [room.id for room in rooms]


async def _resolve_rooms(
    db,
    *,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    all_rooms: bool = False,
) -> list[ResolvedRoom]:
    selectors = [room_id is not None, bool(room_slug), bool(room_name), all_rooms]
    if sum(1 for selected in selectors if selected) != 1:
        raise ValueError("Pass exactly one of --room-id, --room-slug, --room-name, or --all-rooms")

    if room_id is not None:
        result = await db.execute(select(Room.id, Room.slug, Room.name).where(Room.id == room_id))
        row = result.one_or_none()
        if row is None:
            raise ValueError(f"No room found for id {room_id}")
        return [ResolvedRoom(id=row[0], slug=row[1], name=row[2])]

    if room_slug:
        result = await db.execute(select(Room.id, Room.slug, Room.name).where(Room.slug == room_slug))
        row = result.one_or_none()
        if row is None:
            raise ValueError(f"No room found for slug {room_slug!r}")
        return [ResolvedRoom(id=row[0], slug=row[1], name=row[2])]

    if room_name:
        result = await db.execute(
            select(Room.id, Room.slug, Room.name).where(func.lower(Room.name) == room_name.lower())
        )
        rows = list(result.all())
        if not rows:
            raise ValueError(f"No room found for name {room_name!r}")
        if len(rows) > 1:
            matches = ", ".join(f"{row[1]} ({row[0]})" for row in rows)
            raise ValueError(f"Multiple rooms matched name {room_name!r}: {matches}. Use --room-id.")
        row = rows[0]
        return [ResolvedRoom(id=row[0], slug=row[1], name=row[2])]

    result = await db.execute(select(Room.id, Room.slug, Room.name).where(Room.status == "active"))
    rows = result.all()
    rooms = []
    for row in rows:
        if len(row) >= 3:
            rooms.append(ResolvedRoom(id=row[0], slug=row[1], name=row[2]))
        else:
            rooms.append(ResolvedRoom(id=row[0], slug="", name=""))
    return rooms


async def list_embedding_dates(
    *,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
) -> list[dict]:
    settings = get_settings()
    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        result = await db.execute(
            text(
                """
                SELECT
                    CAST(start_msg.created_at AS date) AS embedding_date,
                    COUNT(*) AS batch_count,
                    MIN(start_msg.created_at) AS first_batch_timestamp,
                    MAX(end_msg.created_at) AS last_batch_timestamp
                FROM chat_embeddings ce
                JOIN messages start_msg ON start_msg.id = ce.message_start_id
                JOIN messages end_msg ON end_msg.id = ce.message_end_id
                WHERE ce.source_type = 'message_batch'
                  AND ce.room_id = :room_id
                  AND ce.model_name = :model_name
                  AND ce.model_version = :model_version
                  AND ce.message_start_id IS NOT NULL
                  AND ce.message_end_id IS NOT NULL
                  AND start_msg.is_deleted = FALSE
                  AND end_msg.is_deleted = FALSE
                GROUP BY CAST(start_msg.created_at AS date)
                ORDER BY embedding_date ASC
                """
            ),
            {
                "room_id": str(room.id),
                "model_name": settings.ai_embedding_model,
                "model_version": settings.ai_embedding_provider,
            },
        )
        rows = []
        for row in result.mappings().all():
            rows.append({
                "room_id": str(room.id),
                "room_slug": room.slug,
                "room_name": room.name,
                "date": row["embedding_date"].isoformat() if row["embedding_date"] else None,
                "embedding_batch_count": int(row["batch_count"] or 0),
                "first_batch_timestamp": _iso(row["first_batch_timestamp"]),
                "last_batch_timestamp": _iso(row["last_batch_timestamp"]),
            })
        return rows


async def inspect_date(
    *,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    date_value: date,
    detection_version: str | None = None,
) -> dict:
    settings = get_settings()
    selected_version = detection_version or settings.ai_topic_detection_version
    day_start, day_end = _day_bounds(date_value)
    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        query = (
            select(ChatTopic)
            .options(selectinload(ChatTopic.segments), selectinload(ChatTopic.participants))
            .where(
                ChatTopic.room_id == room.id,
                ChatTopic.status == "active",
                ChatTopic.detection_version == selected_version,
                ChatTopic.bucket_end_at >= day_start,
                ChatTopic.bucket_start_at < day_end,
            )
            .order_by(ChatTopic.bucket_start_at.asc(), ChatTopic.created_at.asc())
        )
        result = await db.execute(query)
        topics = []
        for topic in result.scalars().all():
            segments = sorted(
                getattr(topic, "segments", []) or [],
                key=lambda segment: (segment.started_at or datetime.min, segment.message_start_id or 0),
            )
            participants = sorted(
                getattr(topic, "participants", []) or [],
                key=lambda participant: (
                    -int(getattr(participant, "message_count", 0) or 0),
                    participant.canonical_name.lower(),
                ),
            )
            topics.append({
                "id": str(topic.id),
                "label": topic.label,
                "raw_label": topic.raw_label or topic.label,
                "refined_label": topic.refined_label,
                "display_label": topic.refined_label or topic.label,
                "summary": topic.summary,
                "tags": topic.tags or [],
                "topic_type": topic.topic_type,
                "refinement_model": topic.refinement_model,
                "refined_at": _iso(topic.refined_at),
                "confidence": topic.confidence,
                "generation_type": topic.generation_type,
                "label_source": topic.label_source,
                "topic_date": topic.topic_date.isoformat() if topic.topic_date else None,
                "first_message_at": _iso(topic.first_message_at),
                "last_message_at": _iso(topic.last_message_at),
                "bucket_start_at": _iso(topic.bucket_start_at),
                "bucket_end_at": _iso(topic.bucket_end_at),
                "batch_count": topic.batch_count,
                "participant_count": len(participants),
                "participant_names": [participant.canonical_name for participant in participants],
                "participants": [_participant_payload(participant) for participant in participants],
                "segments": [
                    {
                        "embedding_source_id": segment.embedding_source_id,
                        "message_start_id": segment.message_start_id,
                        "message_end_id": segment.message_end_id,
                        "score": segment.score,
                        "started_at": _iso(segment.started_at),
                        "ended_at": _iso(segment.ended_at),
                        "excerpt": segment.excerpt,
                        "anchor": {
                            "message_id": segment.message_start_id,
                            "url_hint": f"/messages/{segment.message_start_id}" if segment.message_start_id else None,
                        },
                    }
                    for segment in segments
                ],
            })
        return {
            "room_id": str(room.id),
            "room_slug": room.slug,
            "room_name": room.name,
            "date": date_value.isoformat(),
            "detection_version": selected_version,
            "topics": topics,
        }


async def refine_date(
    *,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    date_value: date,
    detection_version: str | None = None,
    topic_id: uuid.UUID | None = None,
    dry_run: bool = False,
    force: bool = False,
    limit_topics: int | None = None,
) -> dict:
    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        service = TopicRefinementService(db)
        result = await service.refine_date(
            room_id=room.id,
            date_value=date_value,
            detection_version=detection_version,
            topic_id=topic_id,
            dry_run=dry_run,
            force=force,
            limit_topics=limit_topics,
        )
        if dry_run:
            await db.rollback()
        else:
            await db.commit()
        return result


async def export_refinement_jobs(
    *,
    output_path: Path,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    date_value: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    detection_version: str | None = None,
    limit_topics: int | None = None,
    include_already_refined: bool = False,
    redaction_value: str | None = None,
    name_mode: str = "canonical",
) -> dict:
    settings = get_settings()
    selected_version = detection_version or settings.ai_topic_detection_version
    windows = _date_windows(date_value=date_value, date_from=date_from, date_to=date_to)
    range_start = windows[0][1]
    range_end = windows[-1][2]
    redaction = parse_redaction(redaction_value)
    if name_mode not in NAME_MODES:
        raise ValueError(f"Unsupported name mode {name_mode!r}")
    max_segments = max(1, int(settings.ai_topic_llm_max_segments))
    max_excerpt_chars = max(100, int(settings.ai_topic_llm_max_excerpt_chars))
    export_id = uuid.uuid4()

    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        repository = TopicDetectionRepository(db)
        aliases = await repository.list_participant_name_aliases(room_id=room.id)
        name_normalizer = NameNormalizer(mode=name_mode, aliases=aliases)
        all_topics = await repository.list_topics_for_refinement_export(
            room_id=room.id,
            date_from=range_start,
            date_to=range_end,
            detection_version=selected_version,
            include_already_refined=True,
        )
        skipped_refined = sum(1 for topic in all_topics if topic.refined_label and not include_already_refined)
        export_topics = [
            topic for topic in all_topics
            if include_already_refined or not topic.refined_label
        ]
        if limit_topics is not None:
            export_topics = export_topics[:max(1, limit_topics)]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_path_for(output_path)
        with output_path.open("w", encoding="utf-8") as handle:
            for topic in export_topics:
                job = build_refinement_job(
                    topic=topic,
                    room_id=room.id,
                    room_slug=room.slug,
                    export_id=export_id,
                    max_segments=max_segments,
                    max_excerpt_chars=max_excerpt_chars,
                    redaction=redaction,
                    name_normalizer=name_normalizer,
                    participants=getattr(topic, "participants", []) or [],
                )
                handle.write(json.dumps(job, sort_keys=True, ensure_ascii=False) + "\n")
        manifest = build_manifest(
            export_id=export_id,
            room_id=room.id,
            room_slug=room.slug,
            date_from=windows[0][0].isoformat(),
            date_to=windows[-1][0].isoformat(),
            detection_version=selected_version,
            topic_count=len(export_topics),
            max_segments=max_segments,
            max_excerpt_chars=max_excerpt_chars,
            redaction=redaction,
            name_mode=name_mode,
        )
        with manifest_path.open("w", encoding="utf-8") as handle:
            json.dump(manifest, handle, sort_keys=True, indent=2)
            handle.write("\n")

    return {
        "status": "ok",
        "room_id": str(room.id),
        "room_slug": room.slug,
        "date_from": windows[0][0].isoformat(),
        "date_to": windows[-1][0].isoformat(),
        "detection_version": selected_version,
        "path": str(output_path),
        "manifest_path": str(manifest_path),
        "export_id": str(export_id),
        "exported": len(export_topics),
        "skipped_refined": skipped_refined,
        "redaction": redaction,
        "name_mode": name_mode,
        "privacy_note": "Export contains private chat excerpts. Store securely and delete after import.",
    }


async def import_refinements(
    *,
    input_path: Path,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    detection_version: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    redaction_value: str | None = None,
    name_mode: str = "canonical",
) -> dict:
    settings = get_settings()
    selected_version = detection_version or settings.ai_topic_detection_version
    redaction = parse_redaction(redaction_value)
    if name_mode not in NAME_MODES:
        raise ValueError(f"Unsupported name mode {name_mode!r}")
    max_segments = max(1, int(settings.ai_topic_llm_max_segments))
    max_excerpt_chars = max(100, int(settings.ai_topic_llm_max_excerpt_chars))
    records = load_jsonl(input_path)

    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        repository = TopicDetectionRepository(db)
        aliases = await repository.list_participant_name_aliases(room_id=room.id)
        name_normalizer = NameNormalizer(mode=name_mode, aliases=aliases)
        per_record = []
        valid_records = 0
        skipped_records = 0
        failed_records = 0
        would_update = 0
        updated = 0
        seen_export_id = None

        for index, record in enumerate(records, start=1):
            parsed, reason = parse_import_record(record, expected_room_id=room.id)
            topic_id = str(record.get("topic_id")) if isinstance(record, dict) else None
            if parsed is None:
                skipped_records += 1
                if reason == "failed_record":
                    failed_records += 1
                per_record.append({"line": index, "topic_id": topic_id, "status": "skipped", "reason": reason})
                continue
            valid_records += 1
            if not parsed.export_id:
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "missing_export_id"})
                continue
            if seen_export_id is None:
                seen_export_id = parsed.export_id
            elif parsed.export_id != seen_export_id:
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "export_id_mismatch"})
                continue

            topic = await repository.get_topic_for_refinement_import(topic_id=parsed.topic_id, room_id=room.id)
            if topic is None:
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "topic_not_found"})
                continue
            if topic.detection_version != selected_version:
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "detection_version_mismatch"})
                continue
            if parsed.topic_date and topic.topic_date and parsed.topic_date != topic.topic_date.isoformat():
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "topic_date_mismatch"})
                continue
            if topic.refined_label and not force:
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "already_refined"})
                continue
            expected_hash = source_hash_from_topic(
                topic=topic,
                room_id=room.id,
                max_segments=max_segments,
                max_excerpt_chars=max_excerpt_chars,
                redaction=redaction,
                name_normalizer=name_normalizer,
            )
            if parsed.source_hash and parsed.source_hash != expected_hash and not force:
                skipped_records += 1
                per_record.append({"line": index, "topic_id": str(parsed.topic_id), "status": "skipped", "reason": "source_hash_mismatch"})
                continue

            would_update += 1
            per_record.append({
                "line": index,
                "topic_id": str(parsed.topic_id),
                "status": "would_update" if dry_run else "updated",
                "refined_label": parsed.proposal.title,
            })
            if not dry_run:
                await repository.apply_refinement(
                    topic=topic,
                    title=parsed.proposal.title,
                    summary=parsed.proposal.summary,
                    tags=parsed.proposal.tags,
                    topic_type=parsed.proposal.topic_type,
                    confidence=parsed.proposal.confidence,
                    refinement_model=parsed.refinement_model,
                )
                if parsed.refined_at:
                    parsed_at = _parse_dt(parsed.refined_at)
                    if parsed_at is not None:
                        topic.refined_at = parsed_at
                updated += 1

        if dry_run:
            await db.rollback()
        else:
            await db.commit()

    return {
        "status": "ok",
        "room_id": str(room.id),
        "room_slug": room.slug,
        "input_path": str(input_path),
        "detection_version": selected_version,
        "dry_run": dry_run,
        "force": force,
        "export_id": seen_export_id,
        "records_read": len(records),
        "valid_records": valid_records,
        "skipped_records": skipped_records,
        "failed_records": failed_records,
        "would_update": would_update,
        "updated": updated,
        "redaction": redaction,
        "name_mode": name_mode,
        "records": per_record,
    }


async def print_settings(
    *,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    similarity_threshold: float | None = None,
    hard_gap_minutes: int | None = None,
    soft_gap_minutes: int | None = None,
    max_topic_duration_hours: int | None = None,
) -> dict:
    settings = get_settings()
    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        service = TopicDetectionService(db)
        room_settings = await service.repository.get_room_settings(room_id=room.id)
        effective = await service.effective_config(
            room_id=room.id,
            similarity_threshold=similarity_threshold,
            hard_gap_minutes=hard_gap_minutes,
            soft_gap_minutes=soft_gap_minutes,
            max_topic_duration_hours=max_topic_duration_hours,
        )
        return {
            "room_id": str(room.id),
            "room_slug": room.slug,
            "room_name": room.name,
            "detection_version": settings.ai_topic_detection_version,
            "generation_type": "semantic_time_cluster",
            "global_config": {
                "similarity_threshold": settings.ai_topic_similarity_threshold,
                "hard_gap_minutes": settings.ai_topic_hard_gap_minutes,
                "soft_gap_minutes": settings.ai_topic_soft_gap_minutes,
                "max_topic_duration_hours": settings.ai_topic_max_topic_duration_hours,
            },
            "room_settings": _room_settings_payload(room_settings),
            "cli_overrides": {
                "similarity_threshold": similarity_threshold,
                "hard_gap_minutes": hard_gap_minutes,
                "soft_gap_minutes": soft_gap_minutes,
                "max_topic_duration_hours": max_topic_duration_hours,
            },
            "effective_config": effective.as_dict(),
        }


async def set_room_similarity_threshold(
    *,
    room_id: uuid.UUID | None = None,
    room_slug: str | None = None,
    room_name: str | None = None,
    similarity_threshold: float,
) -> dict:
    async with async_session_factory() as db:
        rooms = await _resolve_rooms(
            db,
            room_id=room_id,
            room_slug=room_slug,
            room_name=room_name,
            all_rooms=False,
        )
        room = rooms[0]
        logger.info("Resolved room id=%s slug=%s name=%s", room.id, room.slug, room.name)
        service = TopicDetectionService(db)
        row = await service.repository.upsert_room_settings(
            room_id=room.id,
            similarity_threshold=similarity_threshold,
        )
        await db.commit()
        effective = await service.effective_config(room_id=room.id)
        return {
            "room_id": str(room.id),
            "room_slug": room.slug,
            "room_name": room.name,
            "room_settings": _room_settings_payload(row),
            "effective_config": effective.as_dict(),
        }


def _room_settings_payload(row) -> dict | None:
    if row is None:
        return None
    return {
        "enabled": row.enabled,
        "similarity_threshold": row.similarity_threshold,
        "hard_gap_minutes": row.hard_gap_minutes,
        "soft_gap_minutes": row.soft_gap_minutes,
        "max_topic_duration_hours": row.max_topic_duration_hours,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
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
        "first_seen_at": _iso(participant.first_seen_at),
        "last_seen_at": _iso(participant.last_seen_at),
    }


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _day_bounds(value: date) -> tuple[datetime, datetime]:
    start = datetime.combine(value, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _date_windows(
    *,
    date_value: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[tuple[date, datetime, datetime]]:
    if date_value is not None:
        if date_from is not None or date_to is not None:
            raise ValueError("Use either --date or --date-from/--date-to, not both")
        start_day = end_day = date_value
    else:
        if date_from is None and date_to is None:
            raise ValueError("Pass --date or --date-from/--date-to")
        start_day = date_from or date_to
        end_day = date_to or date_from
        if start_day is None or end_day is None:
            raise ValueError("Invalid date range")
    if end_day < start_day:
        raise ValueError("--date-to must be on or after --date-from")

    windows = []
    current = start_day
    while current <= end_day:
        day_start, day_end = _day_bounds(current)
        windows.append((current, day_start, day_end))
        current += timedelta(days=1)
    return windows


def main() -> None:
    parser = argparse.ArgumentParser(prog="friend-hub-topic-detection-worker")
    parser.add_argument("--once", action="store_true", help="Run one detection pass and exit")
    parser.add_argument("--room-id", type=uuid.UUID, default=None, help="Restrict detection to one room")
    parser.add_argument("--room-slug", type=str, default=None, help="Resolve and restrict detection to one room slug")
    parser.add_argument("--room-name", type=str, default=None, help="Resolve and restrict detection to one room name")
    parser.add_argument("--all-rooms", action="store_true", help="Run detection for every active room")
    parser.add_argument("--list-embedding-dates", action="store_true", help="List dates with eligible message_batch embeddings for one room")
    parser.add_argument("--limit-batches", type=int, default=None, help="Maximum embedding batches to scan per room")
    parser.add_argument("--date", type=str, default=None, help="Run one calendar day, YYYY-MM-DD")
    parser.add_argument("--date-from", type=str, default=None, help="Inclusive ISO datetime lower bound")
    parser.add_argument("--date-to", type=str, default=None, help="Inclusive calendar date upper bound, YYYY-MM-DD")
    parser.add_argument("--inspect-date", type=str, default=None, help="Print stored topics and segments for one calendar day")
    parser.add_argument("--refine-date", type=str, default=None, help="Refine stored topics for one calendar day")
    parser.add_argument("--export-refinement-jobs", type=Path, default=None, help="Export private topic refinement jobs JSONL")
    parser.add_argument("--import-refinements", type=Path, default=None, help="Import private topic refinement results JSONL")
    parser.add_argument("--include-already-refined", action="store_true", help="Include already refined topics in refinement export")
    parser.add_argument("--redact", type=str, default=None, help="Comma-separated redaction options for private exports/imports; defaults to urls,emails,phones")
    parser.add_argument("--name-mode", choices=sorted(NAME_MODES), default="canonical", help="Name handling for refinement exports/import hash checks")
    parser.add_argument("--detection-version", type=str, default=None, help="Read/inspect a specific topic detection version")
    parser.add_argument("--topic-id", type=uuid.UUID, default=None, help="Limit refinement to one topic id")
    parser.add_argument("--limit-topics", type=int, default=None, help="Limit number of topics refined in this run")
    parser.add_argument("--force-refine", action="store_true", help="Refine topics even if they already have refined labels")
    parser.add_argument("--similarity-threshold", type=float, default=None, help="Override topic similarity threshold for this run")
    parser.add_argument("--hard-gap-minutes", type=int, default=None, help="Override hard gap minutes for this run")
    parser.add_argument("--soft-gap-minutes", type=int, default=None, help="Override soft gap minutes for this run")
    parser.add_argument("--max-topic-duration-hours", type=int, default=None, help="Override max topic duration hours for this run")
    parser.add_argument("--print-settings", action="store_true", help="Print effective topic detection settings for one room")
    parser.add_argument("--set-similarity-threshold", type=float, default=None, help="Persist room-specific topic similarity threshold")
    parser.add_argument("--dry-run", action="store_true", help="Detect topics without replacing stored topics")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.export_refinement_jobs:
        if args.all_rooms:
            parser.error("--export-refinement-jobs does not support --all-rooms")
        payload = asyncio.run(
            export_refinement_jobs(
                output_path=args.export_refinement_jobs,
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                date_value=_parse_day(args.date),
                date_from=_parse_day(args.date_from),
                date_to=_parse_day(args.date_to),
                detection_version=args.detection_version,
                limit_topics=args.limit_topics,
                include_already_refined=args.include_already_refined,
                redaction_value=args.redact,
                name_mode=args.name_mode,
            )
        )
        print(json.dumps(payload, sort_keys=True))
    elif args.import_refinements:
        if args.all_rooms:
            parser.error("--import-refinements does not support --all-rooms")
        payload = asyncio.run(
            import_refinements(
                input_path=args.import_refinements,
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                detection_version=args.detection_version,
                dry_run=args.dry_run,
                force=args.force_refine,
                redaction_value=args.redact,
                name_mode=args.name_mode,
            )
        )
        print(json.dumps(payload, sort_keys=True))
    elif args.refine_date:
        payload = asyncio.run(
            refine_date(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                date_value=_parse_day(args.refine_date),
                detection_version=args.detection_version,
                topic_id=args.topic_id,
                dry_run=args.dry_run,
                force=args.force_refine,
                limit_topics=args.limit_topics,
            )
        )
        print(json.dumps(payload, sort_keys=True))
    elif args.set_similarity_threshold is not None:
        payload = asyncio.run(
            set_room_similarity_threshold(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                similarity_threshold=args.set_similarity_threshold,
            )
        )
        print(json.dumps(payload, sort_keys=True))
    elif args.print_settings:
        payload = asyncio.run(
            print_settings(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                similarity_threshold=args.similarity_threshold,
                hard_gap_minutes=args.hard_gap_minutes,
                soft_gap_minutes=args.soft_gap_minutes,
                max_topic_duration_hours=args.max_topic_duration_hours,
            )
        )
        print(json.dumps(payload, sort_keys=True))
    elif args.inspect_date:
        payload = asyncio.run(
            inspect_date(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                date_value=_parse_day(args.inspect_date),
                detection_version=args.detection_version,
            )
        )
        print(json.dumps(payload, sort_keys=True))
    elif args.list_embedding_dates:
        rows = asyncio.run(
            list_embedding_dates(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
            )
        )
        for row in rows:
            print(json.dumps(row, sort_keys=True))
    elif args.date or args.date_from or args.date_to:
        results = asyncio.run(
            run_date_backfill(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                all_rooms=args.all_rooms,
                limit_batches=args.limit_batches,
                date_value=_parse_day(args.date),
                date_from=_parse_day(args.date_from),
                date_to=_parse_day(args.date_to),
                dry_run=args.dry_run,
                similarity_threshold=args.similarity_threshold,
                hard_gap_minutes=args.hard_gap_minutes,
                soft_gap_minutes=args.soft_gap_minutes,
                max_topic_duration_hours=args.max_topic_duration_hours,
            )
        )
        for result in results:
            print(json.dumps(result, sort_keys=True))
    else:
        if not args.once:
            parser.error("Pass --once for an unbounded run, or pass --date/--date-from for day-by-day backfill")
        results = asyncio.run(
            run_once(
                room_id=args.room_id,
                room_slug=args.room_slug,
                room_name=args.room_name,
                all_rooms=args.all_rooms,
                limit_batches=args.limit_batches,
                date_from=_parse_dt(args.date_from),
                date_to=_parse_dt(args.date_to),
                dry_run=args.dry_run,
                similarity_threshold=args.similarity_threshold,
                hard_gap_minutes=args.hard_gap_minutes,
                soft_gap_minutes=args.soft_gap_minutes,
                max_topic_duration_hours=args.max_topic_duration_hours,
            )
        )
        for result in results:
            print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
