"""Sender mapping helpers for local Messenger imports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import User

from .encoding import repair_text


def load_sender_map(path: Path | str | None) -> dict[str, dict[str, str]]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Sender map must be a JSON object")

    normalized: dict[str, dict[str, str]] = {}
    for sender_name, mapping in data.items():
        name = repair_text(sender_name).strip()
        if isinstance(mapping, str):
            normalized[name] = {"nickname": mapping}
        elif isinstance(mapping, dict):
            clean = {str(key): str(value) for key, value in mapping.items() if value is not None}
            normalized[name] = clean
        else:
            raise ValueError(f"Invalid sender map entry for {sender_name}")
    return normalized


async def resolve_mapped_user(db: AsyncSession, sender_name: str, sender_map: dict[str, dict[str, str]]) -> User | None:
    mapping = sender_map.get(repair_text(sender_name).strip())
    if not mapping:
        return None

    clauses = []
    if mapping.get("user_id"):
        clauses.append(User.id == mapping["user_id"])
    if mapping.get("session_id"):
        clauses.append(User.session_id == mapping["session_id"])
    if mapping.get("username"):
        clauses.append(User.username == mapping["username"])
    if mapping.get("nickname"):
        clauses.append(User.nickname == mapping["nickname"])
    if not clauses:
        return None

    result = await db.execute(select(User).where(or_(*clauses)))
    return result.scalar_one_or_none()


def mapped_sender_names(sender_map: dict[str, Any]) -> set[str]:
    return {repair_text(name).strip() for name in sender_map}
