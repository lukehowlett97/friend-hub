from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room import Room, RoomMembership, RoomMemberRole


class RoomRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_room_by_slug(self, slug: str) -> Optional[Room]:
        result = await self.db.execute(select(Room).where(Room.slug == slug, Room.status == "active"))
        return result.scalar_one_or_none()

    async def get_room_by_id(self, room_id: UUID) -> Optional[Room]:
        result = await self.db.execute(select(Room).where(Room.id == room_id, Room.status == "active"))
        return result.scalar_one_or_none()

    async def get_membership(self, room_id: UUID, user_id: UUID) -> Optional[RoomMembership]:
        result = await self.db.execute(
            select(RoomMembership).where(
                RoomMembership.room_id == room_id,
                RoomMembership.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_rooms_for_user(self, user_id: UUID) -> list[tuple[Room, RoomMembership]]:
        result = await self.db.execute(
            select(Room, RoomMembership)
            .join(RoomMembership, Room.id == RoomMembership.room_id)
            .where(RoomMembership.user_id == user_id, Room.status == "active")
            .order_by(Room.created_at)
        )
        return result.fetchall()

    async def is_member(self, room_id: UUID, user_id: UUID) -> bool:
        return (await self.get_membership(room_id, user_id)) is not None

    async def is_admin(self, room_id: UUID, user_id: UUID) -> bool:
        m = await self.get_membership(room_id, user_id)
        if not m:
            return False
        return m.role in {RoomMemberRole.admin.value, RoomMemberRole.owner.value}

    async def is_owner(self, room_id: UUID, user_id: UUID) -> bool:
        m = await self.get_membership(room_id, user_id)
        if not m:
            return False
        return m.role == RoomMemberRole.owner.value
