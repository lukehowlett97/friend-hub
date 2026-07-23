"""Discovery for extracted Facebook Messenger exports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .encoding import repair_text
from .models import DiscoveredChat
from .parser import MEDIA_KEYS, find_message_files, load_message_json


def discover_chats(export_dir: Path | str) -> tuple[DiscoveredChat, ...]:
    root = Path(export_dir)
    if not root.exists():
        raise FileNotFoundError(root)

    chats: list[DiscoveredChat] = []
    for chat_dir in sorted({path.parent for path in root.rglob("message_*.json")}):
        chat = inspect_chat(chat_dir)
        if chat is not None:
            chats.append(chat)

    return tuple(chats)


def inspect_chat(chat_dir: Path | str) -> DiscoveredChat | None:
    path = Path(chat_dir)
    message_files = find_message_files(path)
    if not message_files:
        return None

    title = path.name
    thread_path = ""
    participants: set[str] = set()
    message_count = 0
    timestamps: list[int] = []
    has_media = _has_media_dirs(path)

    for message_file in message_files:
        try:
            data = load_message_json(message_file)
        except (OSError, ValueError):
            continue

        if not _looks_like_chat(data):
            continue

        title = repair_text(data.get("title") or title)
        thread_path = data.get("thread_path") or thread_path
        participants.update(_participant_names(data))
        messages = data.get("messages") or []
        message_count += len(messages)
        for raw in messages:
            if not isinstance(raw, dict):
                continue
            timestamp_ms = raw.get("timestamp_ms")
            if isinstance(timestamp_ms, int):
                timestamps.append(timestamp_ms)
            if any(key in raw for key in MEDIA_KEYS):
                has_media = True

    if message_count == 0:
        return None

    return DiscoveredChat(
        title=title,
        thread_path=thread_path or path.name,
        path=path,
        participant_count=len(participants),
        message_count=message_count,
        oldest_at=_datetime_from_ms(min(timestamps)) if timestamps else None,
        newest_at=_datetime_from_ms(max(timestamps)) if timestamps else None,
        has_media=has_media,
        message_files=message_files,
    )


def _looks_like_chat(data: dict[str, Any]) -> bool:
    return isinstance(data.get("participants"), list) and isinstance(data.get("messages"), list)


def _participant_names(data: dict[str, Any]) -> set[str]:
    names = set()
    for participant in data.get("participants") or []:
        if isinstance(participant, dict) and participant.get("name"):
            names.add(repair_text(participant["name"]))
    return names


def _datetime_from_ms(timestamp_ms: int) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None)


def _has_media_dirs(path: Path) -> bool:
    return any((path / dirname).exists() for dirname in ("photos", "gifs", "videos", "audio", "audio_files", "files"))
