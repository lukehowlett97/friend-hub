from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.service import AuthService
from app.domains.chat.connection_manager import ConnectionManager
from app.domains.governance.vote_repository import BOT_NICKNAME, BOT_USER_SESSION_ID
from app.domains.governance.vote_repository import VoteRepository
from app.domains.governance.vote_service import VoteError, VoteService
from app.models.database import get_db_session
from app.models.message import Message, User


router = APIRouter(prefix="/api/v1/governance/votes", tags=["governance"])

AUTH_COOKIE_NAME = "friend_hub_session"


class NicknameVoteCreateRequest(BaseModel):
    target_session_id: str
    proposed_nickname: str
    reason: str | None = None
    expires_at: datetime | None = None


class DisplayRoleVoteCreateRequest(BaseModel):
    target_session_id: str
    proposed_display_role: str
    reason: str | None = None
    expires_at: datetime | None = None


class VoteBallotRequest(BaseModel):
    vote: str


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not isinstance(authorization, str):
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _auth_token(authorization: str | None, session_cookie: str | None = None) -> str | None:
    return _bearer_token(authorization) or session_cookie


def _to_utc_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _is_admin_user(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role in {"owner", "admin"}


async def _current_user_or_401(
    authorization: str | None,
    db: AsyncSession,
    session_cookie: str | None = None,
) -> User:
    auth_service = AuthService(db)
    user, _ = await auth_service.authenticate_token(_auth_token(authorization, session_cookie))
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


_connection_manager: ConnectionManager | None = None


def set_connection_manager(manager: ConnectionManager | None) -> None:
    global _connection_manager
    _connection_manager = manager


def _service(db: AsyncSession) -> VoteService:
    return VoteService(VoteRepository(db), enable_chat_messages=True)


def _raise_vote_error(exc: VoteError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


async def _broadcast_bot_message_by_id(db: AsyncSession, message_id: int | None) -> None:
    if not message_id or _connection_manager is None:
        return
    result = await db.execute(select(Message).where(Message.id == message_id))
    message = result.scalar_one_or_none()
    if not message:
        return
    from app.domains.chat.events import OutgoingChatMessage
    await _connection_manager.broadcast(OutgoingChatMessage(
        session_id=BOT_USER_SESSION_ID,
        nickname=BOT_NICKNAME,
        content=message.content,
        timestamp=message.created_at,
        message_id=message.id,
        is_bot=True,
    ).dict())


@router.post("/nickname")
async def create_nickname_vote(
    request: NicknameVoteCreateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    try:
        vote_action = await _service(db).create_nickname_vote(
            proposer=user,
            target_session_id=request.target_session_id,
            proposed_nickname=request.proposed_nickname,
            reason=request.reason,
            expires_at=_to_utc_naive(request.expires_at),
        )
    except VoteError as exc:
        _raise_vote_error(exc)
    await _broadcast_bot_message_by_id(db, vote_action.get("open_message_id"))
    return {"status": "created", "vote_action": vote_action, "resolved": False}


@router.post("/display-role")
async def create_display_role_vote(
    request: DisplayRoleVoteCreateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    try:
        vote_action = await _service(db).create_display_role_vote(
            proposer=user,
            target_session_id=request.target_session_id,
            proposed_display_role=request.proposed_display_role,
            reason=request.reason,
            expires_at=_to_utc_naive(request.expires_at),
        )
    except VoteError as exc:
        _raise_vote_error(exc)
    await _broadcast_bot_message_by_id(db, vote_action.get("open_message_id"))
    return {"status": "created", "vote_action": vote_action, "resolved": False}


@router.get("")
async def list_votes(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    votes = await _service(db).list_votes(current_user=user)
    return {"vote_actions": votes, "total": len(votes)}


@router.get("/{vote_action_id}")
async def get_vote(
    vote_action_id: int,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    try:
        vote_action = await _service(db).get_vote(vote_action_id=vote_action_id, current_user=user)
    except VoteError as exc:
        _raise_vote_error(exc)
    return {"vote_action": vote_action}


@router.post("/{vote_action_id}/ballot")
async def cast_ballot(
    vote_action_id: int,
    request: VoteBallotRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    try:
        result = await _service(db).cast_vote(vote_action_id=vote_action_id, voter=user, vote=request.vote)
    except VoteError as exc:
        _raise_vote_error(exc)
    if result.get("resolved"):
        await _broadcast_bot_message_by_id(db, result.get("vote_action", {}).get("result_message_id"))
    return {"status": "voted", **result}


@router.post("/{vote_action_id}/cancel")
async def cancel_vote(
    vote_action_id: int,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    try:
        result = await _service(db).cancel_vote(vote_action_id=vote_action_id, actor=user)
    except VoteError as exc:
        _raise_vote_error(exc)
    await _broadcast_bot_message_by_id(db, result.get("vote_action", {}).get("result_message_id"))
    return {"status": "cancelled", **result}


@router.post("/{vote_action_id}/resolve")
async def resolve_vote(
    vote_action_id: int,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    try:
        result = await _service(db).resolve_vote(vote_action_id=vote_action_id, actor=user)
    except VoteError as exc:
        _raise_vote_error(exc)
    if result.get("resolved"):
        await _broadcast_bot_message_by_id(db, result.get("vote_action", {}).get("result_message_id"))
    return {"status": "resolved" if result.get("resolved") else "unchanged", **result}
