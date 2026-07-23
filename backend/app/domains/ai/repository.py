"""Repositories for AI Memory and Suggestions."""
import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_memory import AIMemoryEntry, AISuggestion


class AIMemoryRepository:
    """Repository for AI Memory Entries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        memory_type: str,
        content: str,
        title: Optional[str] = None,
        source_type: Optional[str] = None,
        source_id: Optional[uuid.UUID] = None,
        confidence: Optional[float] = None,
        tags: Optional[List[str]] = None,
        created_by: str = "hub_bot",
        room_id: Optional[uuid.UUID] = None,
        message_start_id: Optional[int] = None,
        message_end_id: Optional[int] = None,
    ) -> AIMemoryEntry:
        """Create a new memory entry."""
        entry = AIMemoryEntry(
            memory_type=memory_type,
            content=content,
            title=title,
            source_type=source_type,
            source_id=source_id,
            confidence=confidence,
            tags=tags or [],
            created_by=created_by,
            room_id=room_id,
            message_start_id=message_start_id,
            message_end_id=message_end_id,
        )
        self.db.add(entry)
        await self.db.flush()
        await self.db.refresh(entry)
        return entry

    async def get_by_id(self, entry_id: uuid.UUID) -> Optional[AIMemoryEntry]:
        """Get a memory entry by ID."""
        return await self.db.get(AIMemoryEntry, entry_id)

    async def list_recent(
        self,
        limit: int = 50,
        memory_type: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> List[AIMemoryEntry]:
        """List recent memory entries with optional filters."""
        stmt = select(AIMemoryEntry).order_by(desc(AIMemoryEntry.created_at))

        if memory_type:
            stmt = stmt.where(AIMemoryEntry.memory_type == memory_type)
        if source_type:
            stmt = stmt.where(AIMemoryEntry.source_type == source_type)

        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_by_ids(self, entry_ids: List[str]) -> List[AIMemoryEntry]:
        """Get memory entries by a list of UUID strings."""
        if not entry_ids:
            return []
        uuids = [uuid.UUID(eid) for eid in entry_ids if eid]
        if not uuids:
            return []
        stmt = select(AIMemoryEntry).where(AIMemoryEntry.id.in_(uuids))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total memory entries."""
        stmt = select(func.count(AIMemoryEntry.id))
        result = await self.db.execute(stmt)
        return result.scalar() or 0

    async def list_summaries_for_gap(
        self,
        room_id: uuid.UUID,
        after_message_id: Optional[int],
        since: datetime,
        limit: int = 10,
    ) -> List[AIMemoryEntry]:
        """List stored summaries covering messages after a read marker.

        Entries without range metadata (legacy rows) fall back to created_at.
        """
        range_clause = and_(
            AIMemoryEntry.message_end_id.is_(None),
            AIMemoryEntry.created_at >= since,
        )
        if after_message_id is not None:
            range_clause = or_(
                AIMemoryEntry.message_end_id > after_message_id,
                range_clause,
            )
        stmt = (
            select(AIMemoryEntry)
            .where(
                AIMemoryEntry.room_id == room_id,
                AIMemoryEntry.memory_type.in_(("daily_summary", "weekly_summary")),
                range_clause,
            )
            .order_by(AIMemoryEntry.created_at)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_entries_for_window(
        self,
        room_id: uuid.UUID,
        day_start: datetime,
        day_end: datetime,
        message_min_id: Optional[int] = None,
        message_max_id: Optional[int] = None,
        limit: int = 10,
    ) -> List[AIMemoryEntry]:
        """Memory entries covering a day: message-range overlap, or created_at
        within the window for rows without range metadata."""
        created_clause = and_(
            AIMemoryEntry.created_at >= day_start,
            AIMemoryEntry.created_at < day_end,
        )
        if message_min_id is not None and message_max_id is not None:
            window_clause = or_(
                and_(
                    AIMemoryEntry.message_start_id.isnot(None),
                    AIMemoryEntry.message_end_id.isnot(None),
                    AIMemoryEntry.message_start_id <= message_max_id,
                    AIMemoryEntry.message_end_id >= message_min_id,
                ),
                and_(AIMemoryEntry.message_end_id.is_(None), created_clause),
            )
        else:
            window_clause = created_clause
        stmt = (
            select(AIMemoryEntry)
            .where(AIMemoryEntry.room_id == room_id, window_clause)
            .order_by(AIMemoryEntry.created_at)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def exists_daily_summary_overlapping(
        self,
        room_id: uuid.UUID,
        message_start_id: int,
        message_end_id: int,
        created_by: str = "daily_summary_job",
    ) -> bool:
        """Whether a scheduled daily summary already covers this message range."""
        stmt = (
            select(AIMemoryEntry.id)
            .where(
                AIMemoryEntry.room_id == room_id,
                AIMemoryEntry.memory_type == "daily_summary",
                AIMemoryEntry.created_by == created_by,
                AIMemoryEntry.message_start_id <= message_end_id,
                AIMemoryEntry.message_end_id >= message_start_id,
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None


class AISuggestionRepository:
    """Repository for AI Suggestions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        suggestion_type: str,
        title: str,
        body: Optional[str] = None,
        proposed_hub_item_type: Optional[str] = None,
        proposed_payload: Optional[dict] = None,
        source_memory_ids: Optional[List[str]] = None,
        status: str = "pending",
    ) -> AISuggestion:
        """Create a new suggestion."""
        suggestion = AISuggestion(
            suggestion_type=suggestion_type,
            title=title,
            body=body,
            status=status,
            proposed_hub_item_type=proposed_hub_item_type,
            proposed_payload=proposed_payload,
            source_memory_ids=source_memory_ids or [],
        )
        self.db.add(suggestion)
        await self.db.flush()
        await self.db.refresh(suggestion)
        return suggestion

    async def get_by_id(self, suggestion_id: uuid.UUID) -> Optional[AISuggestion]:
        """Get a suggestion by ID."""
        return await self.db.get(AISuggestion, suggestion_id)

    async def list_pending(self, limit: int = 50) -> List[AISuggestion]:
        """List pending suggestions."""
        stmt = (
            select(AISuggestion)
            .where(AISuggestion.status == "pending")
            .order_by(desc(AISuggestion.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        suggestion_type: Optional[str] = None,
    ) -> List[AISuggestion]:
        """List recent suggestions with optional filters."""
        stmt = select(AISuggestion).order_by(desc(AISuggestion.created_at))

        if status:
            stmt = stmt.where(AISuggestion.status == status)
        if suggestion_type:
            stmt = stmt.where(AISuggestion.suggestion_type == suggestion_type)

        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        suggestion_id: uuid.UUID,
        status: str,
        created_hub_item_id: Optional[uuid.UUID] = None,
    ) -> Optional[AISuggestion]:
        """Update suggestion status and optionally link to created Hub Item."""
        suggestion = await self.db.get(AISuggestion, suggestion_id)
        if not suggestion:
            return None

        suggestion.status = status
        suggestion.created_hub_item_id = created_hub_item_id
        await self.db.flush()
        await self.db.refresh(suggestion)
        return suggestion

    async def count(self, status: Optional[str] = None) -> int:
        """Count suggestions, optionally filtered by status."""
        stmt = select(func.count(AISuggestion.id))
        if status:
            stmt = stmt.where(AISuggestion.status == status)
        result = await self.db.execute(stmt)
        return result.scalar() or 0