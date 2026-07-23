"""Parser and normalizer for Facebook Messenger message JSON files."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import PROVIDER
from .encoding import repair_text
from .models import NormalizationResult, NormalizedMessage, ParsedMessage


MESSAGE_FILE_PATTERN = "message_*.json"
MEDIA_KEYS = ("photos", "gifs", "videos", "audio_files", "audio", "files", "sticker", "share")


def load_message_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise ValueError(f"{path} is not a Messenger message JSON file")
    return data


def find_message_files(chat_dir: Path) -> tuple[Path, ...]:
    return tuple(sorted(chat_dir.glob(MESSAGE_FILE_PATTERN), key=_message_file_sort_key))


def parse_chat_messages(chat_dir: Path) -> tuple[ParsedMessage, ...]:
    parsed: list[ParsedMessage] = []
    for message_file in find_message_files(chat_dir):
        data = load_message_json(message_file)
        for raw in data.get("messages", []):
            if not isinstance(raw, dict):
                continue
            sender_name = raw.get("sender_name")
            timestamp_ms = raw.get("timestamp_ms")
            if not sender_name or not isinstance(timestamp_ms, int):
                continue
            parsed.append(ParsedMessage(sender_name=sender_name, timestamp_ms=timestamp_ms, raw=raw, source_file=message_file))

    return tuple(sorted(parsed, key=lambda message: message.timestamp_ms))


def normalize_messages(messages: Iterable[ParsedMessage], source_thread_path: str) -> NormalizationResult:
    normalized: list[NormalizedMessage] = []
    skipped_media_count = 0
    skipped_empty_count = 0

    for message in messages:
        raw_content = message.raw.get("content")
        content = repair_text(raw_content).strip() if raw_content is not None else ""
        if not content:
            if _has_media(message.raw):
                skipped_media_count += 1
            else:
                skipped_empty_count += 1
            continue

        sent_at = datetime.fromtimestamp(message.timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        raw_metadata = _metadata_for(message.raw, message.source_file)
        normalized.append(
            NormalizedMessage(
                sender_name=repair_text(message.sender_name).strip(),
                content=content,
                sent_at=sent_at,
                timestamp_ms=message.timestamp_ms,
                source_thread_path=source_thread_path,
                source_hash=source_hash(
                    source_thread_path=source_thread_path,
                    sender_name=message.sender_name,
                    timestamp_ms=message.timestamp_ms,
                    content=content,
                    raw=message.raw,
                ),
                raw_metadata=raw_metadata,
            )
        )

    return NormalizationResult(
        messages=tuple(normalized),
        skipped_media_count=skipped_media_count,
        skipped_empty_count=skipped_empty_count,
    )


def source_hash(source_thread_path: str, sender_name: str, timestamp_ms: int, content: str, raw: dict[str, Any]) -> str:
    payload = {
        "provider": PROVIDER,
        "thread_path": source_thread_path,
        "sender_name": sender_name,
        "timestamp_ms": timestamp_ms,
        "content": content,
        "source_keys": sorted(raw.keys()),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _has_media(raw: dict[str, Any]) -> bool:
    return any(key in raw for key in MEDIA_KEYS) or bool(raw.get("call_duration"))


def _metadata_for(raw: dict[str, Any], source_file: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "source_file": source_file.name,
        "keys": sorted(raw.keys()),
    }
    for key in MEDIA_KEYS:
        if key in raw:
            metadata[key] = raw[key]
    for key in ("is_unsent", "call_duration", "reactions"):
        if key in raw:
            metadata[key] = raw[key]
    return metadata


def _message_file_sort_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    try:
        return int(stem.rsplit("_", 1)[1]), path.name
    except (IndexError, ValueError):
        return 0, path.name
