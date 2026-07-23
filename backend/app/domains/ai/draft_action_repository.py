"""Repository for AI Draft Actions."""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_draft_action import AIDraftAction


class AIDraftActionRepository:
    """Repository for AI Draft Actions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        group_id: int,
        created_by_user_id: uuid.UUID,
        item_type: str,
        title: str,
        payload_json: dict,
        proposed_by: str = "ai",
        action_type: str = "create_hub_item",
        summary: Optional[str] = None,
        source: str = "hub_lab",
        source_message_id: Optional[int] = None,
        agent_run_id: Optional[uuid.UUID] = None,
    ) -> AIDraftAction:
        """Create a new draft action record. Does not commit — caller owns the transaction."""
        draft = AIDraftAction(
            group_id=group_id,
            created_by_user_id=created_by_user_id,
            proposed_by=proposed_by,
            action_type=action_type,
            item_type=item_type,
            status="draft",
            title=title,
            summary=summary,
            payload_json=payload_json,
            source=source,
            source_message_id=source_message_id,
            agent_run_id=agent_run_id,
        )
        self.db.add(draft)
        await self.db.flush()
        await self.db.refresh(draft)
        return draft

    async def get_by_id(
        self,
        draft_id: uuid.UUID,
        group_id: Optional[int] = None,
    ) -> Optional[AIDraftAction]:
        """Fetch a draft action by id, optionally scoped to a group."""
        if group_id is None:
            return await self.db.get(AIDraftAction, draft_id)

        stmt = (
            select(AIDraftAction)
            .where(AIDraftAction.id == draft_id)
            .where(AIDraftAction.group_id == group_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_group(
        self,
        group_id: int,
        status: Optional[str] = None,
        item_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 20,
    ) -> List[AIDraftAction]:
        """List draft actions for a group, newest first."""
        stmt = (
            select(AIDraftAction)
            .where(AIDraftAction.group_id == group_id)
            .order_by(desc(AIDraftAction.created_at))
        )

        if status is not None:
            stmt = stmt.where(AIDraftAction.status == status)
        if item_type is not None:
            stmt = stmt.where(AIDraftAction.item_type == item_type)
        if source is not None:
            stmt = stmt.where(AIDraftAction.source == source)

        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        draft_id: uuid.UUID,
        status: str,
        resolved_by_user_id: Optional[uuid.UUID] = None,
        created_hub_item_id: Optional[uuid.UUID] = None,
        created_poll_id: Optional[int] = None,
        created_event_id: Optional[int] = None,
        created_reminder_id: Optional[int] = None,
    ) -> Optional[AIDraftAction]:
        """Update the status and resolution fields of a draft action.

        Sets resolved_at automatically when status is accepted, rejected, or expired.
        Returns None if the draft is not found.
        """
        draft = await self.db.get(AIDraftAction, draft_id)
        if not draft:
            return None

        draft.status = status
        draft.updated_at = datetime.now(timezone.utc)

        if status in ("accepted", "rejected", "expired"):
            draft.resolved_at = datetime.now(timezone.utc)
            draft.resolved_by_user_id = resolved_by_user_id

        if created_hub_item_id is not None:
            draft.created_hub_item_id = created_hub_item_id
        if created_poll_id is not None:
            draft.created_poll_id = created_poll_id
        if created_event_id is not None:
            draft.created_event_id = created_event_id
        if created_reminder_id is not None:
            draft.created_reminder_id = created_reminder_id

        await self.db.flush()
        await self.db.refresh(draft)
        return draft

    async def mark_accepted(
        self,
        draft_id: uuid.UUID,
        resolved_by_user_id: uuid.UUID,
        created_hub_item_id: Optional[uuid.UUID] = None,
        created_poll_id: Optional[int] = None,
        created_event_id: Optional[int] = None,
        created_reminder_id: Optional[int] = None,
    ) -> Optional[AIDraftAction]:
        """Shorthand for accepting a draft and recording the created item IDs."""
        return await self.update_status(
            draft_id=draft_id,
            status="accepted",
            resolved_by_user_id=resolved_by_user_id,
            created_hub_item_id=created_hub_item_id,
            created_poll_id=created_poll_id,
            created_event_id=created_event_id,
            created_reminder_id=created_reminder_id,
        )

    async def mark_rejected(
        self,
        draft_id: uuid.UUID,
        resolved_by_user_id: uuid.UUID,
    ) -> Optional[AIDraftAction]:
        """Shorthand for rejecting a draft."""
        return await self.update_status(
            draft_id=draft_id,
            status="rejected",
            resolved_by_user_id=resolved_by_user_id,
        )

    async def mark_expired(
        self,
        draft_id: uuid.UUID,
    ) -> Optional[AIDraftAction]:
        """Mark a draft as expired (used by background cleanup jobs)."""
        return await self.update_status(
            draft_id=draft_id,
            status="expired",
        )
