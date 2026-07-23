"""
Archive and restore endpoints for hub items and major item types.
Allows safe deletion by moving items to archive instead of permanently removing them.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_db_session
from app.models.hub_item import HubItem, HubItemStatus
from app.models.planning import Idea, Poll, Reminder
from app.models.event import Event
from app.domains.auth.service import user_payload
from app.models.planning import ActivityAction, ActivityLog

# Create a separate router for archive operations
archive_router = APIRouter(prefix="/api/v1", tags=["archive"])


async def _current_user_or_401(authorization: str | None, db: AsyncSession):
    """Helper to get current user from auth header."""
    from app.api.v1.router import _current_user_or_401 as get_user
    return await get_user(authorization, db)


async def _default_group(db: AsyncSession):
    """Helper to get the default group."""
    from app.api.v1.router import _default_group as get_group
    return await get_group(db)


async def _log_activity(db: AsyncSession, *, group_id: int, actor_user_id, action: ActivityAction, target_type: str, target_id, summary: str):
    """Log activity for audit trail."""
    from app.api.v1.router import _log_activity as log_act
    return await log_act(db, group_id=group_id, actor_user_id=actor_user_id, action=action, target_type=target_type, target_id=target_id, summary=summary)


@archive_router.post("/hub-items/{item_id}/archive")
async def archive_hub_item(
    item_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Archive a hub item (move to archive instead of deleting)."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    from app.api.v1.router import _hub_item_by_id_or_404
    item = await _hub_item_by_id_or_404(db, group.id, item_id)
    
    item.status = HubItemStatus.archived.value
    item.archived_at = datetime.utcnow()
    item.archived_by = user.id
    item.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="hub_item",
        target_id=None,
        summary=f"{user.nickname} archived {item.short_id}",
    )
    await db.commit()
    return {"status": "archived"}


@archive_router.post("/hub-items/{item_id}/restore")
async def restore_hub_item(
    item_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Restore an archived hub item."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    from app.api.v1.router import _hub_item_by_id_or_404
    item = await _hub_item_by_id_or_404(db, group.id, item_id)
    
    if item.status != HubItemStatus.archived.value:
        raise HTTPException(status_code=400, detail="Item is not archived")
    
    item.status = HubItemStatus.open.value
    item.archived_at = None
    item.archived_by = None
    item.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="hub_item",
        target_id=None,
        summary=f"{user.nickname} restored {item.short_id}",
    )
    await db.commit()
    return {"status": "restored"}


@archive_router.get("/hub-items/archived")
async def list_archived_hub_items(
    item_type: str | None = None,
    db: AsyncSession = Depends(get_db_session),
):
    """List all archived hub items, optionally filtered by type."""
    group = await _default_group(db)
    
    from app.api.v1.router import _hub_item_payloads
    items = await _hub_item_payloads(
        db,
        group.id,
        item_type=item_type,
        archived_only=True,
        limit=None,
    )
    return {"items": items, "total": len(items)}


@archive_router.post("/ideas/{idea_id}/archive")
async def archive_idea(
    idea_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Archive an idea."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    idea = await db.get(Idea, idea_id)
    if not idea or idea.group_id != group.id:
        raise HTTPException(status_code=404, detail="Idea not found")
    
    idea.archived_at = datetime.utcnow()
    idea.archived_by = user.id
    idea.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="idea",
        target_id=idea.id,
        summary=f"{user.nickname} archived idea: {idea.title}",
    )
    await db.commit()
    return {"status": "archived"}


@archive_router.post("/ideas/{idea_id}/restore")
async def restore_idea(
    idea_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Restore an archived idea."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    idea = await db.get(Idea, idea_id)
    if not idea or idea.group_id != group.id:
        raise HTTPException(status_code=404, detail="Idea not found")
    
    if not idea.archived_at:
        raise HTTPException(status_code=400, detail="Idea is not archived")
    
    idea.archived_at = None
    idea.archived_by = None
    idea.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="idea",
        target_id=idea.id,
        summary=f"{user.nickname} restored idea: {idea.title}",
    )
    await db.commit()
    return {"status": "restored"}


@archive_router.post("/polls/{poll_id}/archive")
async def archive_poll(
    poll_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Archive a poll."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    poll = await db.get(Poll, poll_id)
    if not poll or poll.group_id != group.id:
        raise HTTPException(status_code=404, detail="Poll not found")
    
    poll.archived_at = datetime.utcnow()
    poll.archived_by = user.id
    poll.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="poll",
        target_id=poll.id,
        summary=f"{user.nickname} archived poll: {poll.question}",
    )
    await db.commit()
    return {"status": "archived"}


@archive_router.post("/polls/{poll_id}/restore")
async def restore_poll(
    poll_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Restore an archived poll."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    poll = await db.get(Poll, poll_id)
    if not poll or poll.group_id != group.id:
        raise HTTPException(status_code=404, detail="Poll not found")
    
    if not poll.archived_at:
        raise HTTPException(status_code=400, detail="Poll is not archived")
    
    poll.archived_at = None
    poll.archived_by = None
    poll.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="poll",
        target_id=poll.id,
        summary=f"{user.nickname} restored poll: {poll.question}",
    )
    await db.commit()
    return {"status": "restored"}


@archive_router.post("/reminders/{reminder_id}/archive")
async def archive_reminder(
    reminder_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Archive a reminder."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    reminder = await db.get(Reminder, reminder_id)
    if not reminder or reminder.group_id != group.id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    
    reminder.archived_at = datetime.utcnow()
    reminder.archived_by = user.id
    reminder.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="reminder",
        target_id=reminder.id,
        summary=f"{user.nickname} archived reminder: {reminder.text[:80]}",
    )
    await db.commit()
    return {"status": "archived"}


@archive_router.post("/reminders/{reminder_id}/restore")
async def restore_reminder(
    reminder_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Restore an archived reminder."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    reminder = await db.get(Reminder, reminder_id)
    if not reminder or reminder.group_id != group.id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    
    if not reminder.archived_at:
        raise HTTPException(status_code=400, detail="Reminder is not archived")
    
    reminder.archived_at = None
    reminder.archived_by = None
    reminder.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="reminder",
        target_id=reminder.id,
        summary=f"{user.nickname} restored reminder: {reminder.text[:80]}",
    )
    await db.commit()
    return {"status": "restored"}


@archive_router.post("/events/{event_id}/archive")
async def archive_event(
    event_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Archive an event."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    event = await db.get(Event, event_id)
    if not event or event.group_id != group.id:
        raise HTTPException(status_code=404, detail="Event not found")
    
    event.archived_at = datetime.utcnow()
    event.archived_by = user.id
    event.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="event",
        target_id=event.id,
        summary=f"{user.nickname} archived event: {event.title}",
    )
    await db.commit()
    return {"status": "archived"}


@archive_router.post("/events/{event_id}/restore")
async def restore_event(
    event_id: int,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
):
    """Restore an archived event."""
    user = await _current_user_or_401(authorization, db)
    group = await _default_group(db)
    
    event = await db.get(Event, event_id)
    if not event or event.group_id != group.id:
        raise HTTPException(status_code=404, detail="Event not found")
    
    if not event.archived_at:
        raise HTTPException(status_code=400, detail="Event is not archived")
    
    event.archived_at = None
    event.archived_by = None
    event.updated_at = datetime.utcnow()
    
    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.updated,
        target_type="event",
        target_id=event.id,
        summary=f"{user.nickname} restored event: {event.title}",
    )
    await db.commit()
    return {"status": "restored"}
