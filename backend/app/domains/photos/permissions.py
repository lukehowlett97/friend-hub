"""Hardcoded permission rules for photo actions on hub items.

The rules:
- Upload: any authenticated user can attach a photo to any hub item.
- Set cover: anyone if the item has no cover yet; otherwise only the
  item creator or an admin/owner can replace it.
- Delete: the photo's uploader, the item creator, or an admin/owner.

A future per-group policy table can replace these helpers without changing
the call sites in the router.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event
from app.models.hub_item import HubItem
from app.models.message import User
from app.models.photo import Photo


def is_admin_or_owner(user: User | None) -> bool:
    if user is None:
        return False
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role in {"owner", "admin"}


async def hub_item_creator_user_id(db: AsyncSession, hub_item: HubItem) -> str | None:
    """Return the canonical user.id (UUID-as-str) of the hub item's creator.

    For most item types this is hub_item.created_by_user_id. Events historically
    track the creator via session_id on the events row, so we resolve through
    the source record when needed.
    """
    if hub_item.created_by_user_id is not None:
        return str(hub_item.created_by_user_id)
    if hub_item.source_type == "event" and hub_item.source_id is not None:
        row = await db.execute(
            select(User.id)
            .join(Event, Event.created_by_session_id == User.session_id)
            .where(Event.id == hub_item.source_id)
        )
        creator_id = row.scalar_one_or_none()
        return str(creator_id) if creator_id else None
    return None


async def is_item_creator(db: AsyncSession, user: User, hub_item: HubItem) -> bool:
    creator_id = await hub_item_creator_user_id(db, hub_item)
    return creator_id is not None and creator_id == str(user.id)


def can_upload_photo(user: User | None) -> bool:
    return user is not None


async def can_set_cover(db: AsyncSession, user: User, hub_item: HubItem) -> bool:
    if hub_item.cover_photo_id is None:
        return user is not None
    if is_admin_or_owner(user):
        return True
    return await is_item_creator(db, user, hub_item)


async def can_delete_photo(
    db: AsyncSession, user: User, photo: Photo, hub_item: HubItem | None
) -> bool:
    if user is None:
        return False
    if is_admin_or_owner(user):
        return True
    if photo.uploaded_by_session_id and photo.uploaded_by_session_id == user.session_id:
        return True
    if hub_item is not None and await is_item_creator(db, user, hub_item):
        return True
    return False
