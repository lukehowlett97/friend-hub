"""Internal data shapes for Messenger imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DiscoveredChat:
    title: str
    thread_path: str
    path: Path
    participant_count: int
    message_count: int
    oldest_at: datetime | None
    newest_at: datetime | None
    has_media: bool
    message_files: tuple[Path, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "thread_path": self.thread_path,
            "path": str(self.path),
            "participant_count": self.participant_count,
            "message_count": self.message_count,
            "oldest_at": self.oldest_at.isoformat() if self.oldest_at else None,
            "newest_at": self.newest_at.isoformat() if self.newest_at else None,
            "has_media": self.has_media,
            "message_files": [str(path) for path in self.message_files],
        }


@dataclass(frozen=True)
class ParsedMessage:
    sender_name: str
    timestamp_ms: int
    raw: dict[str, Any]
    source_file: Path


@dataclass(frozen=True)
class NormalizedMessage:
    sender_name: str
    content: str
    sent_at: datetime
    timestamp_ms: int
    source_thread_path: str
    source_hash: str
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizationResult:
    messages: tuple[NormalizedMessage, ...]
    skipped_media_count: int
    skipped_empty_count: int
