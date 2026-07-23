from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.rooms.repository import RoomRepository
from app.models.room import Room, RoomMembership


class RoomService:
    def __init__(self, db: AsyncSession):
        self.repository = RoomRepository(db)

    async def get_rooms_for_user(self, user_id: UUID) -> list[dict]:
        rows = await self.repository.get_rooms_for_user(user_id)
        return [_room_payload(room, membership) for room, membership in rows]

    async def resolve_room(
        self,
        *,
        slug: Optional[str],
        user_id: UUID,
    ) -> tuple[Optional[Room], Optional[str]]:
        """
        Resolve which room to use for a request.

        Resolution order:
        1. If slug is provided: look up the room, verify membership.
        2. If slug is missing and user belongs to exactly one room: use it.
        3. If slug is missing and user belongs to multiple rooms: return an error.

        Returns (room, error_message).  One of the two is always None.
        """
        if slug:
            room = await self.repository.get_room_by_slug(slug)
            if not room:
                return None, "Room not found"
            if not await self.repository.is_member(room.id, user_id):
                return None, "You are not a member of this room"
            return room, None

        rows = await self.repository.get_rooms_for_user(user_id)
        if not rows:
            return None, "You are not a member of any room"
        if len(rows) == 1:
            return rows[0][0], None
        return None, "Multiple rooms available — send X-Room-Slug header to select one"


def _room_payload(room: Room, membership: RoomMembership) -> dict:
    return {
        "id": str(room.id),
        "slug": room.slug,
        "name": room.name,
        "status": room.status,
        "role": membership.role,
        "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
    }
