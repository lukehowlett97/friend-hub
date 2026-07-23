"""Group Lore service — search and phrase stats over chat messages.

Phase 1: exact, case-insensitive phrase search across native + imported
chat messages. Designed as a vertical slice — future phases can add fuzzy
search, date filters, timeline buckets, and AI summaries on top.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.imported_identity import ImportedIdentity
from app.models.message import Message, User

logger = logging.getLogger(__name__)

SNIPPET_PADDING = 60
SNIPPET_MAX = 240
MAX_LIMIT = 100
STATS_SCAN_CAP = 5000


def _normalise_query(q: Optional[str]) -> str:
    if not q:
        return ""
    return q.strip()


def _build_snippet(content: str, match_start: int, match_len: int) -> tuple[str, int]:
    """Return (snippet, match_offset_within_snippet)."""
    if not content:
        return "", 0
    start = max(0, match_start - SNIPPET_PADDING)
    end = min(len(content), match_start + match_len + SNIPPET_PADDING)
    snippet = content[start:end]
    prefix = ""
    if start > 0:
        prefix = "…"
        snippet = prefix + snippet
    if end < len(content):
        snippet = snippet + "…"
    offset = (match_start - start) + len(prefix)
    if len(snippet) > SNIPPET_MAX:
        snippet = snippet[:SNIPPET_MAX] + "…"
    return snippet, offset


def _to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Message.created_at is stored naive in UTC — match that on filtering."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _count_occurrences(content: str, needle_lower: str) -> int:
    if not content or not needle_lower:
        return 0
    return content.lower().count(needle_lower)


def _effective_user(msg: Message, user: User | None, linked_user: User | None = None) -> User | None:
    if getattr(msg, "is_imported", False) and linked_user is not None:
        return linked_user
    return user


class GroupLoreService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def search_messages(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict:
        """Exact phrase, case-insensitive search across chat messages.

        Returns: {"query", "results": [...], "total", "limit", "offset"}.
        Blank queries return an empty result with total=0.

        ``date_from`` is inclusive; ``date_to`` is exclusive — callers wanting
        "messages on 2026-05-12" pass ``date_to=2026-05-13`` to avoid the
        usual end-of-day off-by-one.
        """
        q = _normalise_query(query)
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        date_from = _to_naive_utc(date_from)
        date_to = _to_naive_utc(date_to)

        # Blank query is allowed — it browses the archive within the date
        # window. Highlight metadata simply degrades (match_start=0, length=0).
        base_filter = Message.is_deleted.is_(False)
        if q:
            base_filter = base_filter & Message.content.ilike(f"%{q}%")
        if date_from is not None:
            base_filter = base_filter & (Message.created_at >= date_from)
        if date_to is not None:
            base_filter = base_filter & (Message.created_at < date_to)

        total_result = await self.db.execute(
            select(func.count(Message.id)).where(base_filter)
        )
        total = int(total_result.scalar() or 0)

        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        rows_result = await self.db.execute(
            select(Message, User, LinkedUser)
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .where(base_filter)
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        rows = rows_result.fetchall()

        needle_lower = q.lower()
        results = []
        for row in rows:
            if len(row) >= 3:
                msg, user, linked_user = row[:3]
            else:
                msg, user = row
                linked_user = None
            effective_user = _effective_user(msg, user, linked_user)
            content = msg.content or ""
            if needle_lower:
                content_lower = content.lower()
                match_start = content_lower.find(needle_lower)
                snippet, snippet_match_start = _build_snippet(
                    content, match_start if match_start >= 0 else 0, len(q)
                )
                match_count = content_lower.count(needle_lower)
            else:
                # No query → show the start of the message as the snippet,
                # truncated to keep cards compact in browse mode.
                snippet = content if len(content) <= SNIPPET_MAX else content[:SNIPPET_MAX] + "…"
                snippet_match_start = 0
                match_count = 0
            effective_user_id = getattr(effective_user, "id", None) if effective_user else None
            effective_session_id = getattr(effective_user, "session_id", None) if effective_user else None
            message_user_id = getattr(msg, "user_id", None)
            results.append({
                "message_id": msg.id,
                "chat_id": None,  # native chat is a single group room; reserved for future multi-chat support
                "sender_session_id": str(effective_session_id or msg.user_session_id),
                "sender_user_id": str(effective_user_id) if effective_user_id else str(message_user_id) if message_user_id else None,
                "sender_nickname": effective_user.nickname if effective_user else "Unknown",
                "sender_username": getattr(effective_user, "username", None) if effective_user else None,
                "sender_avatar_url": getattr(effective_user, "avatar_url", None) if effective_user else None,
                "sender_avatar_emoji": getattr(effective_user, "avatar_emoji", None) if effective_user else None,
                "content": content,
                "snippet": snippet,
                "match_start": snippet_match_start,
                "match_length": len(q),
                "match_count": match_count,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "is_imported": bool(getattr(msg, "is_imported", False)),
            })

        return {
            "query": q,
            "results": results,
            "total": total,
            "limit": limit,
            "offset": offset,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        }

    async def phrase_stats(
        self,
        query: str,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> dict:
        """Count phrase occurrences across messages, grouped by sender.

        Counts every occurrence (a message containing the phrase three times
        contributes three to its sender's total), not just matching messages.
        """
        q = _normalise_query(query)
        date_from = _to_naive_utc(date_from)
        date_to = _to_naive_utc(date_to)
        if not q:
            return {
                "query": q,
                "total_occurrences": 0,
                "matching_messages": 0,
                "people": 0,
                "results": [],
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
            }

        pattern = f"%{q}%"
        where_clause = (
            (Message.is_deleted.is_(False))
            & (Message.content.ilike(pattern))
        )
        if date_from is not None:
            where_clause = where_clause & (Message.created_at >= date_from)
        if date_to is not None:
            where_clause = where_clause & (Message.created_at < date_to)

        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        rows_result = await self.db.execute(
            select(Message, User, LinkedUser)
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .where(where_clause)
            .order_by(desc(Message.created_at))
            .limit(STATS_SCAN_CAP)
        )
        rows = rows_result.fetchall()

        needle_lower = q.lower()
        per_sender: dict[str, dict] = {}
        total_occurrences = 0
        matching_messages = 0

        for row in rows:
            if len(row) >= 3:
                msg, user, linked_user = row[:3]
            else:
                msg, user = row
                linked_user = None
            effective_user = _effective_user(msg, user, linked_user)
            occ = _count_occurrences(msg.content or "", needle_lower)
            if occ <= 0:
                continue
            matching_messages += 1
            total_occurrences += occ
            effective_user_id = getattr(effective_user, "id", None) if effective_user else None
            effective_session_id = getattr(effective_user, "session_id", None) if effective_user else None
            message_user_id = getattr(msg, "user_id", None)
            key = str(effective_session_id or msg.user_session_id)
            bucket = per_sender.get(key)
            if bucket is None:
                bucket = {
                    "sender_session_id": key,
                    "sender_user_id": str(effective_user_id) if effective_user_id else str(message_user_id) if message_user_id else None,
                    "sender_nickname": effective_user.nickname if effective_user else "Unknown",
                    "sender_username": getattr(effective_user, "username", None) if effective_user else None,
                    "sender_avatar_url": getattr(effective_user, "avatar_url", None) if effective_user else None,
                    "sender_avatar_emoji": getattr(effective_user, "avatar_emoji", None) if effective_user else None,
                    "count": 0,
                    "message_count": 0,
                }
                per_sender[key] = bucket
            bucket["count"] += occ
            bucket["message_count"] += 1

        results = sorted(
            per_sender.values(),
            key=lambda r: (-r["count"], r["sender_nickname"].lower() if r["sender_nickname"] else ""),
        )

        return {
            "query": q,
            "total_occurrences": total_occurrences,
            "matching_messages": matching_messages,
            "people": len(results),
            "results": results,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        }
