from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.domains.topic_detection.refinement import (
    JOB_SCHEMA_VERSION,
    RESULT_SCHEMA_VERSION,
    TopicRefinementResult,
    validate_refinement,
)

MANIFEST_SCHEMA_VERSION = "topic_refinement_export_manifest_v1"
JOB_RECORD_TYPE = "topic_job"
RESULT_RECORD_TYPE = "topic_refinement"
DEFAULT_REDACTION = ("urls", "emails", "phones")
NAME_MODES = {"canonical", "display", "anonymous"}


class NameNormalizer:
    def __init__(self, *, mode: str = "canonical", aliases: dict[str, str] | None = None):
        if mode not in NAME_MODES:
            raise ValueError(f"Unsupported name mode {mode!r}")
        self.mode = mode
        self.aliases = aliases or {}
        self._anonymous: dict[str, str] = {}

    def normalize_label(self, value: str | None) -> str:
        text = value or ""
        if self.mode == "display":
            return text
        return _replace_names_in_text(text, self._replacement_for)

    def normalize_excerpt(self, value: str | None) -> str:
        text = value or ""
        if self.mode == "display":
            return text

        def replace_prefix(match: re.Match) -> str:
            return f"{match.group(1)}{self._replacement_for(match.group(2))}:"

        text = re.sub(r"(\[[^\]]+\]\s+)([^:\n]{1,80}):", replace_prefix, text)
        return _replace_names_in_text(text, self._replacement_for)

    def _replacement_for(self, display_name: str) -> str:
        display = " ".join(str(display_name or "").strip().split())
        if not display:
            return display
        if self.mode == "anonymous":
            if display not in self._anonymous:
                self._anonymous[display] = f"Participant {len(self._anonymous) + 1}"
            return self._anonymous[display]
        return self.aliases.get(display, display)


@dataclass(frozen=True)
class RefinementImportRecord:
    topic_id: uuid.UUID
    room_id: uuid.UUID
    source_hash: str | None
    export_id: str | None
    topic_date: str | None
    refinement_model: str
    refined_at: str | None
    proposal: TopicRefinementResult


def parse_redaction(value: str | None) -> list[str]:
    if value is None or value.strip() == "":
        return list(DEFAULT_REDACTION)
    allowed = {"urls", "emails", "phones", "names"}
    redaction = []
    for part in value.split(","):
        item = part.strip().lower()
        if not item:
            continue
        if item not in allowed:
            raise ValueError(f"Unsupported redaction option {item!r}")
        if item not in redaction:
            redaction.append(item)
    return redaction


def redact_text(value: str | None, redaction: Iterable[str]) -> str:
    text = (value or "").replace("\x00", "")
    options = set(redaction)
    if "urls" in options:
        text = re.sub(r"https?://\S+|www\.\S+", "[url]", text)
    if "emails" in options:
        text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[email]", text, flags=re.I)
    if "phones" in options:
        text = re.sub(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", "[phone]", text)
    if "names" in options:
        text = re.sub(r"(\[[^\]]+\]\s+)[^:\n]{1,40}:", r"\1[name]:", text)
    return text


def build_manifest(
    *,
    export_id: uuid.UUID,
    room_id: uuid.UUID,
    room_slug: str,
    date_from: str,
    date_to: str,
    detection_version: str,
    topic_count: int,
    max_segments: int,
    max_excerpt_chars: int,
    redaction: list[str],
    name_mode: str,
) -> dict:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "export_id": str(export_id),
        "room_id": str(room_id),
        "room_slug": room_slug,
        "date_from": date_from,
        "date_to": date_to,
        "detection_version": detection_version,
        "topic_count": topic_count,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "max_segments": max_segments,
        "max_excerpt_chars": max_excerpt_chars,
        "redaction": redaction,
        "name_mode": name_mode,
    }


def build_refinement_job(
    *,
    topic,
    room_id: uuid.UUID,
    room_slug: str,
    export_id: uuid.UUID,
    max_segments: int,
    max_excerpt_chars: int,
    redaction: list[str],
    name_normalizer: NameNormalizer | None = None,
    participants: list | None = None,
) -> dict:
    name_normalizer = name_normalizer or NameNormalizer(mode="display")
    segments = _topic_segments(
        topic=topic,
        max_segments=max_segments,
        max_excerpt_chars=max_excerpt_chars,
        redaction=redaction,
        name_normalizer=name_normalizer,
    )
    job = {
        "schema_version": JOB_SCHEMA_VERSION,
        "record_type": JOB_RECORD_TYPE,
        "export_id": str(export_id),
        "topic_id": str(topic.id),
        "room_id": str(room_id),
        "room_slug": room_slug,
        "topic_date": topic.topic_date.isoformat() if topic.topic_date else None,
        "detection_version": topic.detection_version,
        "generation_type": topic.generation_type,
        "raw_label": name_normalizer.normalize_label(topic.raw_label or topic.label),
        "current_label": name_normalizer.normalize_label(topic.refined_label or topic.label),
        "confidence": topic.confidence,
        "started_at": _iso(topic.first_message_at or topic.bucket_start_at),
        "ended_at": _iso(topic.last_message_at or topic.bucket_end_at),
        "segments": segments,
        "participants": _topic_participants(
            participants=participants or getattr(topic, "participants", []) or [],
            name_normalizer=name_normalizer,
        ),
        "limits": {
            "max_segments": max_segments,
            "max_excerpt_chars": max_excerpt_chars,
        },
    }
    job["source_hash"] = source_hash_from_job(job)
    return job


def normalize_participant_name(*, participant, name_normalizer: NameNormalizer) -> str:
    name = getattr(participant, "canonical_name", None) or getattr(participant, "display_name", None) or ""
    if name_normalizer.mode == "display":
        return getattr(participant, "display_name", None) or name
    return name_normalizer._replacement_for(name)


def source_hash_from_topic(
    *,
    topic,
    room_id: uuid.UUID,
    max_segments: int,
    max_excerpt_chars: int,
    redaction: list[str],
    name_normalizer: NameNormalizer | None = None,
) -> str:
    name_normalizer = name_normalizer or NameNormalizer(mode="display")
    job = {
        "topic_id": str(topic.id),
        "room_id": str(room_id),
        "topic_date": topic.topic_date.isoformat() if topic.topic_date else None,
        "detection_version": topic.detection_version,
        "segments": _topic_segments(
            topic=topic,
            max_segments=max_segments,
            max_excerpt_chars=max_excerpt_chars,
            redaction=redaction,
            name_normalizer=name_normalizer,
        ),
    }
    return _sha256(job)


def source_hash_from_job(job: dict) -> str:
    return _sha256({
        "topic_id": job.get("topic_id"),
        "room_id": job.get("room_id"),
        "topic_date": job.get("topic_date"),
        "detection_version": job.get("detection_version"),
        "segments": job.get("segments") or [],
    })


def manifest_path_for(output_path: Path) -> Path:
    suffix = "".join(output_path.suffixes)
    if suffix.endswith(".jsonl"):
        return output_path.with_name(output_path.name[:-6] + ".manifest.json")
    return output_path.with_suffix(output_path.suffix + ".manifest.json")


def load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                records.append({
                    "_line_number": line_number,
                    "_invalid_json": str(exc),
                })
    return records


def parse_import_record(record: dict, *, expected_room_id: uuid.UUID) -> tuple[RefinementImportRecord | None, str | None]:
    if record.get("_invalid_json"):
        return None, f"invalid_json: {record['_invalid_json']}"
    if record.get("schema_version") != RESULT_SCHEMA_VERSION:
        return None, "invalid_schema_version"
    if record.get("record_type") != RESULT_RECORD_TYPE:
        return None, "invalid_record_type"
    if record.get("status") == "failed":
        return None, "failed_record"
    if record.get("status") not in (None, "refined"):
        return None, "invalid_status"
    try:
        topic_id = uuid.UUID(str(record.get("topic_id")))
        room_id = uuid.UUID(str(record.get("room_id")))
    except (TypeError, ValueError):
        return None, "invalid_uuid"
    if room_id != expected_room_id:
        return None, "room_mismatch"
    try:
        proposal = validate_refinement({
            "title": record.get("refined_label"),
            "summary": record.get("summary"),
            "tags": record.get("tags"),
            "topic_type": record.get("topic_type"),
            "confidence": record.get("confidence"),
        })
    except Exception as exc:
        return None, f"invalid_refinement: {exc}"
    return RefinementImportRecord(
        topic_id=topic_id,
        room_id=room_id,
        source_hash=record.get("source_hash"),
        export_id=record.get("export_id"),
        topic_date=record.get("topic_date"),
        refinement_model=str(record.get("refinement_model") or "local:unknown"),
        refined_at=record.get("refined_at"),
        proposal=proposal,
    ), None


def _topic_segments(
    *,
    topic,
    max_segments: int,
    max_excerpt_chars: int,
    redaction: list[str],
    name_normalizer: NameNormalizer,
) -> list[dict]:
    segments = sorted(
        getattr(topic, "segments", []) or [],
        key=lambda segment: (segment.started_at or datetime.min, segment.message_start_id or 0),
    )
    payload = []
    for segment in segments[:max(1, max_segments)]:
        excerpt = name_normalizer.normalize_excerpt(segment.excerpt)
        excerpt = redact_text(excerpt, redaction)[:max(100, max_excerpt_chars)]
        payload.append({
            "segment_id": getattr(segment, "id", None),
            "started_at": _iso(segment.started_at),
            "ended_at": _iso(segment.ended_at),
            "score": segment.score,
            "excerpt": excerpt,
        })
    return payload


def _topic_participants(*, participants: list, name_normalizer: NameNormalizer) -> list[dict]:
    payload = []
    for participant in sorted(
        participants,
        key=lambda item: (-int(getattr(item, "message_count", 0) or 0), str(getattr(item, "canonical_name", "")).lower()),
    ):
        canonical_name = normalize_participant_name(participant=participant, name_normalizer=name_normalizer)
        if not canonical_name:
            continue
        display_name = getattr(participant, "display_name", None)
        if name_normalizer.mode in {"anonymous", "canonical"}:
            display_name = canonical_name
        payload.append({
            "canonical_name": canonical_name,
            "display_name": display_name,
            "message_count": int(getattr(participant, "message_count", 0) or 0),
            "segment_count": int(getattr(participant, "segment_count", 0) or 0),
            "first_seen_at": _iso(getattr(participant, "first_seen_at", None)),
            "last_seen_at": _iso(getattr(participant, "last_seen_at", None)),
        })
    return payload


def _sha256(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _replace_names_in_text(text: str, replacement_for) -> str:
    names = []
    if hasattr(replacement_for, "__self__"):
        names = list(getattr(replacement_for.__self__, "aliases", {}).keys())
    for name in sorted((name for name in names if name), key=len, reverse=True):
        replacement = replacement_for(name)
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", replacement, text)
    return text
