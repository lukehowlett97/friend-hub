"""
FastAPI dependency functions for room-scoped access control.

Usage in route handlers:
    room = Depends(get_current_room)
    room = Depends(require_room_member)   # same as above — alias for clarity
    room = Depends(require_room_admin)
    room = Depends(require_room_owner)
"""
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.service import AuthService
from app.models.database import get_db_session
from app.models.message import User
from app.models.room import Room
from app.domains.rooms.repository import RoomRepository
from app.domains.rooms.service import RoomService

AUTH_COOKIE_NAME = "friend_hub_session"


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not isinstance(authorization, str):
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    auth_service = AuthService(db)
    token = _bearer_token(authorization)
    user = None
    if token:
        user, _ = await auth_service.authenticate_token(token)
    if user is None and session_cookie and session_cookie != token:
        user, _ = await auth_service.authenticate_token(session_cookie)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def get_current_room(
    x_room_slug: Optional[str] = Header(default=None, alias="X-Room-Slug"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> Room:
    """
    Resolve and return the current room from the X-Room-Slug header.
    Membership is verified against the authenticated user.
    """
    return await room_for_user(user=user, db=db, slug=x_room_slug)


async def room_for_user(
    user: User,
    db: AsyncSession,
    slug: Optional[str],
) -> Room:
    """
    Resolve current room for an already-authenticated user.
    Raises HTTPException on any access/resolution failure.
    """
    service = RoomService(db)
    room, error = await service.resolve_room(slug=slug, user_id=user.id)
    if error:
        # 404 for "not found / not a member of any room", 400 for ambiguity
        if "not found" in error or "not a member" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)
    return room


async def require_room_admin_for_user(user: User, room: Room, db: AsyncSession) -> None:
    repo = RoomRepository(db)
    if not await repo.is_admin(room.id, user.id):
        raise HTTPException(status_code=403, detail="Room admin access required")


async def require_room_owner_for_user(user: User, room: Room, db: AsyncSession) -> None:
    repo = RoomRepository(db)
    if not await repo.is_owner(room.id, user.id):
        raise HTTPException(status_code=403, detail="Room owner access required")


async def require_room_member(room: Room = Depends(get_current_room)) -> Room:
    return room


async def require_room_admin(
    user: User = Depends(get_current_user),
    room: Room = Depends(get_current_room),
    db: AsyncSession = Depends(get_db_session),
) -> Room:
    await require_room_admin_for_user(user, room, db)
    return room


async def require_room_owner(
    user: User = Depends(get_current_user),
    room: Room = Depends(get_current_room),
    db: AsyncSession = Depends(get_db_session),
) -> Room:
    await require_room_owner_for_user(user, room, db)
    return room
