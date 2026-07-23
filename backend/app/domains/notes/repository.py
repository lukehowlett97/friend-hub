from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hub_item import HubItem
from app.models.message import User
from app.models.note import Note, NoteRevision
from app.models.planning import Comment


class NoteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def next_room_sequence(self, room_id: UUID) -> int:
        result = await self.db.execute(
            select(func.max(Note.room_sequence)).where(Note.room_id == room_id)
        )
        return (result.scalar() or 0) + 1

    async def get(self, note_id: int, room_id: UUID, *, include_archived: bool = False) -> Note | None:
        stmt = select(Note).where(Note.id == note_id, Note.room_id == room_id)
        if not include_archived:
            stmt = stmt.where(Note.archived_at.is_(None))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        room_id: UUID,
        *,
        q: str | None = None,
        note_type: str | None = None,
        pinned: bool | None = None,
        sort: str = "updated",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[tuple[Note, User | None, HubItem | None]], int]:
        stmt = (
            select(Note, User, HubItem)
            .outerjoin(User, Note.created_by_user_id == User.id)
            .outerjoin(HubItem, (HubItem.source_type == "note") & (HubItem.source_id == Note.id) & (HubItem.room_id == Note.room_id))
            .where(Note.room_id == room_id, Note.archived_at.is_(None))
        )
        count_stmt = select(func.count(Note.id)).where(Note.room_id == room_id, Note.archived_at.is_(None))
        if q:
            pat = f"%{q}%"
            clause = or_(Note.title.ilike(pat), Note.body.ilike(pat))
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)
        if note_type:
            stmt = stmt.where(Note.note_type == note_type)
            count_stmt = count_stmt.where(Note.note_type == note_type)
        if pinned is not None:
            stmt = stmt.where(HubItem.pinned_to_home.is_(pinned))
            count_stmt = count_stmt.where(
                Note.id.in_(
                    select(HubItem.source_id).where(
                        HubItem.room_id == room_id,
                        HubItem.source_type == "note",
                        HubItem.pinned_to_home.is_(pinned),
                    )
                )
            )
        if sort == "created":
            stmt = stmt.order_by(HubItem.pinned_to_home.desc(), desc(Note.created_at))
        else:
            stmt = stmt.order_by(HubItem.pinned_to_home.desc(), desc(Note.updated_at))
        total = (await self.db.execute(count_stmt)).scalar() or 0
        rows = (await self.db.execute(stmt.limit(limit).offset(offset))).fetchall()
        return rows, total

    async def get_hub_item(self, note_id: int, room_id: UUID) -> HubItem | None:
        return (await self.db.execute(
            select(HubItem).where(
                HubItem.room_id == room_id,
                HubItem.source_type == "note",
                HubItem.source_id == note_id,
            )
        )).scalar_one_or_none()

    async def comment_counts(self, note_ids: list[int]) -> dict[int, int]:
        if not note_ids:
            return {}
        rows = (await self.db.execute(
            select(Comment.target_id, func.count(Comment.id))
            .where(Comment.target_type == "note", Comment.target_id.in_(note_ids))
            .group_by(Comment.target_id)
        )).fetchall()
        return {target_id: count for target_id, count in rows}

    async def revision_counts(self, note_ids: list[int]) -> dict[int, int]:
        if not note_ids:
            return {}
        rows = (await self.db.execute(
            select(NoteRevision.note_id, func.count(NoteRevision.id))
            .where(NoteRevision.note_id.in_(note_ids))
            .group_by(NoteRevision.note_id)
        )).fetchall()
        return {note_id: count for note_id, count in rows}
