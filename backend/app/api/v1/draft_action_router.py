"""API endpoints for AI Draft Actions.

Draft actions are AI-proposed Events, Polls, and Reminders that only become
real app items after an explicit user confirm step (accept). The AI may only
propose (status='draft'); a user must accept or reject.
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.router import AUTH_COOKIE_NAME, _current_user_or_401, _default_group
from app.domains.ai.draft_action_service import (
    DraftActionService,
    DraftActionNotFoundError,
    DraftActionValidationError,
    DraftActionInvalidStatusError,
)
from app.models.ai_draft_action import AIDraftAction
from app.models.database import get_db_session

router = APIRouter(prefix="/api/v1/ai/draft-actions", tags=["ai-draft-actions"])


# ── Response schemas ──────────────────────────────────────────────────────────


class DraftActionResponse(BaseModel):
    id: str
    group_id: int
    created_by_user_id: str
    resolved_by_user_id: str | None
    proposed_by: str
    action_type: str
    item_type: str
    status: str
    title: str
    summary: str | None
    payload_json: dict
    source: str
    source_message_id: int | None
    agent_run_id: str | None
    created_hub_item_id: str | None
    created_poll_id: int | None
    created_event_id: int | None
    created_reminder_id: int | None
    created_at: str | None
    updated_at: str | None
    resolved_at: str | None


class DraftActionsResponse(BaseModel):
    draft_actions: list[DraftActionResponse]
    total: int


class UpdateDraftActionRequest(BaseModel):
    title: str | None = None
    payload_json: dict | None = None


class UpdateDraftActionResponse(BaseModel):
    draft_action: DraftActionResponse


class AcceptDraftActionResponse(BaseModel):
    success: bool
    draft_action: DraftActionResponse
    message: str


class RejectDraftActionResponse(BaseModel):
    success: bool
    draft_action: DraftActionResponse
    message: str


# ── Serialiser ────────────────────────────────────────────────────────────────


def _draft_payload(draft: AIDraftAction) -> dict:
    return {
        "id": str(draft.id),
        "group_id": draft.group_id,
        "created_by_user_id": str(draft.created_by_user_id) if draft.created_by_user_id else None,
        "resolved_by_user_id": str(draft.resolved_by_user_id) if draft.resolved_by_user_id else None,
        "proposed_by": draft.proposed_by,
        "action_type": draft.action_type,
        "item_type": draft.item_type,
        "status": draft.status,
        "title": draft.title,
        "summary": draft.summary,
        "payload_json": draft.payload_json or {},
        "source": draft.source,
        "source_message_id": draft.source_message_id,
        "agent_run_id": str(draft.agent_run_id) if draft.agent_run_id else None,
        "created_hub_item_id": str(draft.created_hub_item_id) if draft.created_hub_item_id else None,
        "created_poll_id": draft.created_poll_id,
        "created_event_id": draft.created_event_id,
        "created_reminder_id": draft.created_reminder_id,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
        "resolved_at": draft.resolved_at.isoformat() if draft.resolved_at else None,
    }


# ── Exception mapper ──────────────────────────────────────────────────────────


def _map_service_error(exc: Exception) -> HTTPException:
    """Convert domain exceptions to HTTP responses."""
    if isinstance(exc, DraftActionNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DraftActionValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, DraftActionInvalidStatusError):
        return HTTPException(status_code=409, detail=str(exc))
    raise exc  # re-raise anything unexpected


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=DraftActionsResponse)
async def list_draft_actions(
    status: Optional[str] = None,
    item_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 20,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """List AI draft actions for the default group, newest first."""
    await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    svc = DraftActionService(db)
    drafts = await svc.list_draft_actions(
        group_id=group.id,
        status=status,
        item_type=item_type,
        source=source,
        limit=min(limit, 100),
    )
    return DraftActionsResponse(
        draft_actions=[DraftActionResponse(**_draft_payload(d)) for d in drafts],
        total=len(drafts),
    )


@router.get("/{draft_action_id}", response_model=DraftActionResponse)
async def get_draft_action(
    draft_action_id: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Fetch a single AI draft action, scoped to the default group."""
    await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)

    try:
        draft_uuid = uuid.UUID(draft_action_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid draft action ID")

    svc = DraftActionService(db)
    draft = await svc.get_draft_action(draft_uuid, group_id=group.id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft action not found")

    return DraftActionResponse(**_draft_payload(draft))


@router.patch("/{draft_action_id}", response_model=UpdateDraftActionResponse)
async def update_draft_action(
    draft_action_id: str,
    body: UpdateDraftActionRequest,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Update the title and/or payload of a draft action before accepting."""
    await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)

    try:
        draft_uuid = uuid.UUID(draft_action_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid draft action ID")

    svc = DraftActionService(db)
    draft = await svc.get_draft_action(draft_uuid, group_id=group.id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft action not found")
    if draft.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft-status actions can be edited")

    new_payload = dict(body.payload_json) if body.payload_json is not None else dict(draft.payload_json or {})

    if body.title is not None:
        new_title = body.title.strip() or draft.title
        draft.title = new_title
        # Keep payload_json title fields in sync so accept methods always get the right value
        for key in ("title", "question", "text"):
            if key in new_payload:
                new_payload[key] = new_title

    if body.payload_json is not None or body.title is not None:
        try:
            svc._validate_payload(draft.item_type, new_payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        draft.payload_json = new_payload

    await db.commit()
    await db.refresh(draft)
    return UpdateDraftActionResponse(draft_action=DraftActionResponse(**_draft_payload(draft)))


@router.post("/{draft_action_id}/accept", response_model=AcceptDraftActionResponse)
async def accept_draft_action(
    draft_action_id: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Accept a draft action, creating the real Hub Item.

    The canonical domain row (Poll / Event / Reminder) and its hub_items mirror
    are created inside DraftActionService.accept_draft_action(). The session is
    committed here after the service returns successfully.
    """
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)

    try:
        draft_uuid = uuid.UUID(draft_action_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid draft action ID")

    svc = DraftActionService(db)
    try:
        updated = await svc.accept_draft_action(
            draft_uuid,
            resolved_by_user_id=user.id,
            group_id=group.id,
        )
    except (DraftActionNotFoundError, DraftActionValidationError, DraftActionInvalidStatusError) as exc:
        raise _map_service_error(exc)

    await db.commit()
    await db.refresh(updated)

    item_type_label = updated.item_type.capitalize()
    return AcceptDraftActionResponse(
        success=True,
        draft_action=DraftActionResponse(**_draft_payload(updated)),
        message=f"{item_type_label} created from draft.",
    )


@router.post("/{draft_action_id}/reject", response_model=RejectDraftActionResponse)
async def reject_draft_action(
    draft_action_id: str,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Reject a draft action. No canonical item is created."""
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)

    try:
        draft_uuid = uuid.UUID(draft_action_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid draft action ID")

    svc = DraftActionService(db)
    try:
        updated = await svc.reject_draft_action(
            draft_uuid,
            resolved_by_user_id=user.id,
            group_id=group.id,
        )
    except (DraftActionNotFoundError, DraftActionInvalidStatusError) as exc:
        raise _map_service_error(exc)

    await db.commit()
    await db.refresh(updated)

    return RejectDraftActionResponse(
        success=True,
        draft_action=DraftActionResponse(**_draft_payload(updated)),
        message="Draft action rejected.",
    )
