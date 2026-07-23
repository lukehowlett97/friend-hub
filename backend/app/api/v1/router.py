"""
Main API router for v1 endpoints.
Contains all REST API routes separated from WebSocket logic.
"""
import json
import uuid
import base64
import binascii
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, desc, func, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import aliased

from app.config import get_photo_upload_path, get_settings
from app.models.database import get_db_session
from app.models.event import Event, EventInvite, EventRsvp
from app.models.room import DEFAULT_ROOM_ID, Room, RoomMembership, RoomSettings
from app.models.hub_item import HubItem, HubItemStatus, HubItemType
from app.models.home_appearance import HomeAppearance
from app.models.member import GroupMember
from app.models.message import Message, User
from app.models.imported_identity import ImportedIdentity
from app.models.import_tracking import ImportedMessageSource
from app.models.photo import Photo
from app.models.planning import (
    ActivityAction,
    ActivityLog,
    Comment,
    DEFAULT_GROUP_SLUG,
    EventPost,
    Group,
    Idea,
    IdeaStatus,
    ItemHistory,
    POLL_SOURCE_CHAT_AGENDA,
    Poll,
    PollEventType,
    PollOption,
    PollStatus,
    PollVote,
    PollVoteMode,
    Reminder,
    ReminderAssignee,
)
from app.models.notification import Notification
from app.models.note import Note
from app.models.push_subscription import PushSubscription
from app.models.reaction import Reaction
from app.models.video import AudioFile
from app.models.database import async_session_factory
from app.services.chat_service import ChatService
from app.domains.messages.service import MessageService
from app.domains.members.service import MemberService
from app.domains.auth.service import AuthService, admin_user_payload, user_payload
from app.domains.chat.connection_manager import ConnectionManager
from app.domains.identity.detection import detect_user_cleanup_candidate
from app.domains.identity.schemas import (
    ImportedIdentityCreate,
    ImportedIdentityLinkRequest,
    ImportedIdentityUpdate,
    UserCleanupUpdate,
)
from app.domains.identity.service import IdentityService
from app.domains.hub_items.references import find_hub_item_references
from app.domains.events.calendar import build_event_ics
from app.domains.photos.service import ensure_photo_storage_capacity, process_photo_upload
from app.domains.photos import permissions as photo_permissions
from app.domains.ai.search_ask_service import (
    MAX_QUESTION_CHARS,
    MAX_SNIPPET_CHARS,
    MAX_SOURCES,
    SearchAskService,
    SearchAskSource,
    make_source_id,
    normalize_source_type,
    truncate_text,
)
from app.services.tags import normalize_tags


# Create API router
router = APIRouter(prefix="/api/v1")

# Pydantic models for API requests/responses
class SessionRequest(BaseModel):
    nickname: str

class SessionResponse(BaseModel):
    session_id: str
    nickname: str
    status: str

class AuthRegisterRequest(BaseModel):
    username: str
    nickname: str
    invite_code: str

class ClaimInviteRequest(BaseModel):
    invite_code: str
    pin: str
    pin_confirm: str


def _request_base_url(request: Request | None = None) -> str:
    if request is not None:
        forwarded_host = request.headers.get("x-forwarded-host")
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        if forwarded_host:
            return f"{forwarded_proto or request.url.scheme}://{forwarded_host}".rstrip("/")

        origin = request.headers.get("origin")
        if origin:
            return origin.rstrip("/")

        host = request.headers.get("host")
        if host:
            return f"{request.url.scheme}://{host}".rstrip("/")

    return get_settings().app_base_url.rstrip("/")


def _invite_url(invite_code: str, request: Request | None = None) -> str:
    base = _request_base_url(request)
    return f"{base}/join/{invite_code}"

class PinLoginRequest(BaseModel):
    username: str
    pin: str

class AdminUserCreateRequest(BaseModel):
    display_name: str
    username: str
    role: str = "member"
    room_ids: list[uuid.UUID] = []
    room_role: str = "member"

class AdminRoleUpdateRequest(BaseModel):
    role: str

class AdminUserRoomUpdateRequest(BaseModel):
    role: str = "member"

class AdminUserProfileUpdateRequest(BaseModel):
    username: str | None = None


def _imported_identity_payload(identity) -> dict:
    linked_user = getattr(identity, "__dict__", {}).get("linked_user")
    return {
        "id": str(identity.id),
        "source": identity.source,
        "source_participant_id": identity.source_participant_id,
        "source_display_name": identity.source_display_name,
        "normalised_name": identity.normalised_name,
        "linked_user_id": str(identity.linked_user_id) if identity.linked_user_id else None,
        "linked_user": {
            "id": str(linked_user.id),
            "username": linked_user.username,
            "display_name": linked_user.display_name or linked_user.nickname,
        } if linked_user else None,
        "status": identity.status,
        "message_count": identity.message_count,
        "first_seen_at": identity.first_seen_at,
        "last_seen_at": identity.last_seen_at,
        "confidence_score": identity.confidence_score,
        "notes": identity.notes,
        "created_at": identity.created_at,
        "updated_at": identity.updated_at,
    }


def _identity_user_payload(item: dict) -> dict:
    user = item["user"]
    suggestion = item.get("suggestion") or detect_user_cleanup_candidate(user, item.get("message_count", 0))
    return {
        **admin_user_payload(user),
        "session_id": str(user.session_id),
        "nickname": user.nickname,
        "message_count": item.get("message_count", 0),
        "likely_test_user": suggestion.likely_test_user,
        "cleanup_suggestion": suggestion.cleanup_suggestion,
        "suggestion_reason": suggestion.suggestion_reason,
    }


async def _admin_user_room_payloads(db: AsyncSession, users: list[User]) -> tuple[dict[str, list[dict]], list[dict]]:
    user_ids = [user.id for user in users if user.id]
    if not user_ids:
        return {}, []

    result = await db.execute(
        select(Room, RoomMembership)
        .join(RoomMembership, Room.id == RoomMembership.room_id)
        .where(RoomMembership.user_id.in_(user_ids))
        .order_by(Room.name.asc(), Room.created_at.asc())
    )

    rooms_by_user: dict[str, list[dict]] = {str(user.id): [] for user in users if user.id}
    rooms_by_id: dict[str, dict] = {}
    for room, membership in result.fetchall():
        room_payload = {
            "id": str(room.id),
            "slug": room.slug,
            "name": room.name,
            "status": room.status,
        }
        rooms_by_id[str(room.id)] = room_payload
        rooms_by_user.setdefault(str(membership.user_id), []).append({
            **room_payload,
            "role": membership.role,
            "joined_at": membership.joined_at.isoformat() if membership.joined_at else None,
        })

    return rooms_by_user, list(rooms_by_id.values())

class AuthUserResponse(BaseModel):
    id: str
    session_id: str
    username: str | None = None
    nickname: str
    display_name: str | None = None
    role: str
    is_admin: bool = False
    is_owner: bool = False
    avatar_url: str | None = None
    is_guest: bool = False

class AvatarUploadRequest(BaseModel):
    data_url: str

class AuthResponse(BaseModel):
    user: AuthUserResponse
    token: str | None = None

class ProfileUpdateRequest(BaseModel):
    nickname: str

class MessagesResponse(BaseModel):
    messages: list
    total: int
    limit: int
    offset: int

class ReadStateUpdate(BaseModel):
    message_id: int

class MemberResponse(BaseModel):
    id: str | None = None
    session_id: str
    username: str | None = None
    nickname: str
    role: str
    is_online: bool
    is_imported: bool = False
    message_count: int
    joined_at: str | None = None
    last_seen: str | None = None

class MembersResponse(BaseModel):
    members: list
    total: int
    unlinked_imported_members: list = Field(default_factory=list)


class SearchAskVisibleResult(BaseModel):
    type: str
    id: str | int
    title: str | None = None
    snippet: str | None = None
    author: str | None = None
    created_at: str | None = None
    route: str | None = None
    reference: str | None = None


class SearchAskRequest(BaseModel):
    question: str
    search_query: str = ""
    filters: list[str] = []
    visible_results: list[SearchAskVisibleResult] = []


class SearchAskSourceResponse(BaseModel):
    type: str
    id: str
    title: str
    snippet: str
    route: str | None = None
    reference: str | None = None


class SearchAskResponse(BaseModel):
    answer: str
    sources: list[SearchAskSourceResponse]
    request_id: str

class RoleUpdateRequest(BaseModel):
    role: str

class ProfileMetadataUpdateRequest(BaseModel):
    nickname: str | None = None
    display_role: str | None = None
    bio: str | None = None
    avatar_emoji: str | None = None

class EventCreateRequest(BaseModel):
    title: str
    starts_at: datetime
    description: str | None = None
    location: str | None = None
    cover_photo_url: str | None = None
    photo_tag_id: str | None = None
    linked_poll_id: int | None = None

class EventUpdateRequest(BaseModel):
    title: str | None = None
    starts_at: datetime | None = None
    description: str | None = None
    location: str | None = None
    cover_photo_url: str | None = None
    photo_tag_id: str | None = None
    linked_poll_id: int | None = None
    tags: list[str] | None = None

class EventInviteUpdateRequest(BaseModel):
    user_ids: list[str] = []

class RsvpRequest(BaseModel):
    response: str

class IdeaCreateRequest(BaseModel):
    title: str
    description: str | None = None
    category: str = "general"
    status: str = "maybe"

class IdeaUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    category: str | None = None
    status: str | None = None
    tags: list[str] | None = None

class PollCreateRequest(BaseModel):
    question: str
    options: list[str]
    vote_mode: str = "single"
    deadline_at: datetime | None = None
    linked_idea_id: int | None = None
    linked_event_id: int | None = None

class PollUpdateRequest(BaseModel):
    question: str | None = None
    deadline_at: datetime | None = None
    voting_opens_at: datetime | None = None
    linked_idea_id: int | None = None
    linked_event_id: int | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None

class PollVoteRequest(BaseModel):
    option_ids: list[int]

class ChatEventCreateRequest(BaseModel):
    event_type: str
    voting_opens_at: datetime
    voting_closes_at: datetime
    title: str | None = None
    description: str | None = None
    target_user_id: str | None = None
    proposed_nickname: str | None = None
    proposed_role: str | None = None
    poll_question: str | None = None
    poll_options: list[str] | None = None

class ReminderCreateRequest(BaseModel):
    title: str | None = None
    text: str | None = None
    due_at: datetime
    context: str | None = None
    linked_event_id: int | None = None
    assignee_user_ids: list[str] = []
    recurrence: str | None = None          # None | 'daily' | 'weekly' | 'every_N_days'
    recurrence_days: int | None = None     # N when recurrence='every_N_days'
    recurrence_ends_at: datetime | None = None

class ReminderUpdateRequest(BaseModel):
    title: str | None = None
    text: str | None = None
    context: str | None = None
    due_at: datetime | None = None
    linked_event_id: int | None = None
    assignee_user_ids: list[str] | None = None
    tags: list[str] | None = None
    recurrence: str | None = None
    recurrence_days: int | None = None
    recurrence_ends_at: datetime | None = None

class ReminderCompleteRequest(BaseModel):
    is_completed: bool = True

class CommentCreateRequest(BaseModel):
    target_type: str
    target_id: int
    content: str

class CommentUpdateRequest(BaseModel):
    content: str

class EventPostCreateRequest(BaseModel):
    content: str

class ReactionToggleRequest(BaseModel):
    target_type: str
    target_id: int
    emoji: str

class HubItemCreateRequest(BaseModel):
    type: str = "note"
    title: str
    body: str | None = None
    tags: list[str] = []
    due_at: datetime | None = None
    event_start_at: datetime | None = None
    event_end_at: datetime | None = None
    assigned_to_user_id: str | None = None

class HubItemUpdateRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None
    short_id: str | None = None
    status: str | None = None
    pinned_to_home: bool | None = None
    due_at: datetime | None = None
    event_start_at: datetime | None = None
    event_end_at: datetime | None = None
    assigned_to_user_id: str | None = None

class HubItemPinRequest(BaseModel):
    pinned: bool

class PhotoUploadRequest(BaseModel):
    filename: str
    content_type: str
    data_url: str
    caption: str | None = None
    tags: list[str] = []
    event_id: int | None = None
    hub_item_id: str | None = None
    tag_id: str | None = None  # legacy; prefer tags[]


class CoverPhotoPositionRequest(BaseModel):
    x: int
    y: int


class HomeAppearanceUpdateRequest(BaseModel):
    cover_photo_id: int | None = None
    cover_position_x: int | None = None
    cover_position_y: int | None = None
    overlay_strength: int | None = None
    blur_enabled: bool | None = None
    header_icon: str | None = None


class HomeAppearanceSetCoverRequest(BaseModel):
    photo_id: int

class HealthResponse(BaseModel):
    status: str
    connections: int
    database: str

class PushSubscriptionRequest(BaseModel):
    endpoint: str
    p256dh_key: str
    auth_key: str
    user_agent: str | None = None


class NotificationPreferencesUpdate(BaseModel):
    chat_messages: bool | None = None
    chat_mentions: bool | None = None
    polls: bool | None = None
    events: bool | None = None
    reminders: bool | None = None
    comments: bool | None = None
    reactions: bool | None = None
    hub_bot: bool | None = None
    push_enabled: bool | None = None
    email_enabled: bool | None = None


def _to_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _iso_utc(value: datetime | None) -> str | None:
    """ISO-format a naive UTC datetime with an explicit Z suffix so the
    browser parses it as UTC instead of local time (the ECMAScript default
    for ISO strings without a timezone designator)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not isinstance(authorization, str):
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


AUTH_COOKIE_NAME = "friend_hub_session"


def _auth_token(authorization: str | None, session_cookie: str | None = None) -> str | None:
    cookie = session_cookie if isinstance(session_cookie, str) and session_cookie.strip() else None
    return _bearer_token(authorization) or cookie


async def _authenticate_request(
    auth_service: AuthService,
    authorization: str | None,
    session_cookie: str | None = None,
) -> tuple[User | None, object | None]:
    bearer = _bearer_token(authorization)
    cookie = session_cookie if isinstance(session_cookie, str) and session_cookie.strip() else None
    if bearer:
        user, session = await auth_service.authenticate_token(bearer)
        if user:
            return user, session
    if cookie and cookie != bearer:
        return await auth_service.authenticate_token(cookie)
    return None, None


def _set_auth_cookie(response: Response, token: str, *, session_only: bool = False) -> None:
    settings = get_settings()
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        **({} if session_only else {"max_age": 60 * 60 * 24 * AuthService.SESSION_DAYS}),
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", httponly=True, samesite="lax")


def _ensure_not_demo_guest(user: User) -> None:
    if getattr(user, "user_type", None) == "guest":
        raise HTTPException(status_code=403, detail="This feature is unavailable in the public demo")


# Dependency to get connection manager
# This will be injected from main.py
_connection_manager: ConnectionManager = None

def get_connection_manager() -> ConnectionManager:
    """Get the connection manager instance."""
    return _connection_manager

def set_connection_manager(manager: ConnectionManager):
    """Set the connection manager instance."""
    global _connection_manager
    _connection_manager = manager


async def _current_user_or_401(authorization: str | None, db: AsyncSession, session_cookie: str | None = None) -> User:
    auth_service = AuthService(db)
    user, _ = await _authenticate_request(auth_service, authorization, session_cookie)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def _current_admin_user_or_403(authorization: str | None, db: AsyncSession, session_cookie: str | None = None) -> User:
    user = await _current_user_or_401(authorization, db, session_cookie)
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def _current_owner_user_or_403(authorization: str | None, db: AsyncSession, session_cookie: str | None = None) -> User:
    user = await _current_user_or_401(authorization, db, session_cookie)
    if not _is_owner_user(user):
        raise HTTPException(status_code=403, detail="Owner access required")
    return user


async def _default_group(db: AsyncSession) -> Group:
    result = await db.execute(select(Group).where(Group.slug == DEFAULT_GROUP_SLUG))
    group = result.scalar_one_or_none()
    if group:
        return group
    group = Group(name="Friend Hub", slug=DEFAULT_GROUP_SLUG)
    db.add(group)
    await db.flush()
    return group


def _user_payload_from_row(user_id, username, nickname, role, avatar_url=None) -> dict | None:
    if not user_id:
        return None
    role_value = role.value if hasattr(role, "value") else role
    return {
        "id": str(user_id),
        "username": username,
        "nickname": nickname,
        "role": role_value or "member",
        "avatar_url": avatar_url,
    }


async def _valid_session_id_or_none(db: AsyncSession, session_id: str | None):
    if not session_id or not isinstance(session_id, str) or not hasattr(db, "execute"):
        return None
    result = await db.execute(select(User.session_id).where(User.session_id == session_id))
    return result.scalar_one_or_none()


def _clean_text(value: str | None, *, field: str, max_length: int) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return text[:max_length]


def _optional_url(value: str | None, *, max_length: int = 500) -> str | None:
    url = (value or "").strip()
    if not url:
        return None
    if len(url) > max_length:
        raise HTTPException(status_code=400, detail="URL is too long")
    if not (url.startswith("/") or url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="URL must be a local path or http(s) URL")
    return url


def _optional_tag_id(value: str | None, *, max_length: int = 40) -> str | None:
    tag = (value or "").strip()
    if not tag:
        return None
    tag = tag[:max_length]
    if not all(char.isalnum() or char in {"#", "-", "_"} for char in tag):
        raise HTTPException(status_code=400, detail="Tag ID can only use letters, numbers, #, -, and _")
    return tag


def _optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text[:max_length] if text else None


def _validate_target_type(target_type: str) -> str:
    target = target_type.strip().lower()
    if target not in {"idea", "poll", "event", "reminder", "note", "comment", "event_post"}:
        raise HTTPException(status_code=400, detail="Unsupported target type")
    return target


def _field_was_set(model: BaseModel, field_name: str) -> bool:
    fields_set = getattr(model, "model_fields_set", None)
    if fields_set is None:
        fields_set = getattr(model, "__fields_set__", set())
    return field_name in fields_set


def _reminder_title_from_request(request: ReminderCreateRequest | ReminderUpdateRequest) -> str | None:
    title = request.title if _field_was_set(request, "title") else None
    if title is None and _field_was_set(request, "text"):
        title = request.text
    return title


async def _target_exists(
    db: AsyncSession,
    target_type: str,
    target_id: int,
    group_id: int,
    *,
    room_id=None,
) -> bool:
    model_map = {
        "idea": Idea,
        "poll": Poll,
        "event": Event,
        "reminder": Reminder,
        "note": Note,
    }
    if target_type == "comment":
        comment = await db.get(Comment, target_id)
        if not comment or comment.group_id != group_id:
            return False
        if room_id is None:
            return True
        try:
            parent_target = _validate_target_type(comment.target_type)
        except HTTPException:
            return False
        return await _target_exists(
            db,
            parent_target,
            comment.target_id,
            group_id,
            room_id=room_id,
        )
    if target_type == "event_post":
        stmt = (
            select(EventPost.id)
            .join(Event, Event.id == EventPost.event_id)
            .where(EventPost.id == target_id, EventPost.group_id == group_id)
        )
        if room_id is not None:
            stmt = stmt.where(Event.room_id == room_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none() is not None

    model = model_map[target_type]
    stmt = select(model.id).where(model.id == target_id)
    if hasattr(model, "group_id"):
        stmt = stmt.where(model.group_id == group_id)
    if room_id is not None and hasattr(model, "room_id"):
        stmt = stmt.where(model.room_id == room_id)
    if hasattr(model, "archived_at"):
        stmt = stmt.where(model.archived_at.is_(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def _is_admin_user(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role in {"owner", "admin"}


def _is_owner_user(user: User) -> bool:
    role = user.role.value if hasattr(user.role, "value") else user.role
    return role == "owner"


def _clean_room_member_role(role: str, *, username: str | None = None) -> str:
    normalized = (role or "member").strip().lower()
    if normalized not in {"owner", "admin", "member"}:
        raise HTTPException(status_code=400, detail="Room role must be owner, admin, or member")
    if normalized == "owner" and (username or "").strip().lower() != "techlett":
        raise HTTPException(status_code=400, detail="Only techlett can be a room owner")
    return normalized


async def _admin_user_response(db: AsyncSession, user: User) -> dict:
    rooms_by_user, _rooms = await _admin_user_room_payloads(db, [user])
    return {
        **admin_user_payload(user),
        "rooms": rooms_by_user.get(str(user.id), []),
    }


def _can_edit_event(user: User, event: Event) -> bool:
    return _is_admin_user(user) or event.created_by_session_id == user.session_id


def _can_manage_creator_owned_item(user: User, created_by_user_id) -> bool:
    return _is_admin_user(user) or (created_by_user_id is not None and str(created_by_user_id) == str(user.id))


def _require_event_editor(user: User, event: Event):
    if not _can_edit_event(user, event):
        raise HTTPException(status_code=403, detail="Only the event creator or admins can edit this event")


HUB_ITEM_PREFIXES = {
    "idea": "I",
    "poll": "P",
    "reminder": "R",
    "event": "E",
    "note": "N",
}


import re as _re  # local alias to avoid clashing with any nearby `re` import order
_SHORT_ID_BODY_RE = _re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,18}$")


def _clean_short_id(value: str) -> str:
    """Validate and normalise a user-supplied short_id (chat reference tag)."""
    if value is None:
        raise HTTPException(status_code=400, detail="Reference tag is required")
    candidate = value.strip()
    if candidate.startswith("#"):
        candidate = candidate[1:]
    if not _SHORT_ID_BODY_RE.match(candidate):
        raise HTTPException(
            status_code=400,
            detail="Reference tag must start with a letter and contain only letters, numbers, hyphens or underscores (2-19 chars)",
        )
    return f"#{candidate}"


async def _ensure_short_id_unique(db: AsyncSession, group_id: int, short_id: str, exclude_item_id, room_id=None) -> None:
    stmt = select(HubItem.id).where(
        HubItem.group_id == group_id,
        func.upper(HubItem.short_id) == short_id.upper(),
    )
    if room_id is not None:
        stmt = stmt.where(HubItem.room_id == room_id)
    if exclude_item_id is not None:
        stmt = stmt.where(HubItem.id != exclude_item_id)
    existing = (await db.execute(stmt)).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Reference tag {short_id} is already in use")


def _clean_tags(tags: list[str] | None) -> list[str]:
    """Normalize tags for storage (trimmed, lowercased, deduplicated)."""
    return normalize_tags(tags, max_tags=8, max_length=40)


def _hub_item_status_from_legacy(item_type: str, value=None, *, is_completed: bool | None = None) -> str:
    if item_type == "reminder":
        return HubItemStatus.done.value if is_completed else HubItemStatus.open.value
    if item_type == "idea":
        return HubItemStatus.done.value if str(value) == "done" else HubItemStatus.open.value
    return HubItemStatus.open.value


async def _next_hub_item_sequence(db: AsyncSession, item_type: str, room_id=None) -> int:
    stmt = select(func.max(HubItem.type_sequence)).where(HubItem.item_type == item_type)
    if room_id is not None:
        stmt = stmt.where(HubItem.room_id == room_id)
    result = await db.execute(stmt)
    return (result.scalar() or 0) + 1


async def _hub_item_for_source(
    db: AsyncSession,
    *,
    group_id: int,
    item_type: str,
    source_id: int,
    title: str,
    body: str | None = None,
    tags: list[str] | None = None,
    status: str = HubItemStatus.open.value,
    created_by_user_id=None,
    assigned_to_user_id=None,
    due_at: datetime | None = None,
    event_start_at: datetime | None = None,
    event_end_at: datetime | None = None,
    room_id=None,
) -> HubItem:
    if room_id is None:
        room_id = DEFAULT_ROOM_ID
    result = await db.execute(
        select(HubItem).where(
            HubItem.source_type == item_type,
            HubItem.source_id == source_id,
            HubItem.room_id == room_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        item = HubItem(
            group_id=group_id,
            room_id=room_id,
            item_type=item_type,
            type_sequence=source_id,
            short_id=f"#{HUB_ITEM_PREFIXES[item_type]}-{source_id}",
            source_type=item_type,
            source_id=source_id,
            created_by_user_id=created_by_user_id,
        )
        db.add(item)

    item.title = title[:220]
    item.body = body
    if tags is not None:
        item.tags = _clean_tags(tags)
    elif item.tags is None:
        item.tags = []
    item.status = status
    item.assigned_to_user_id = assigned_to_user_id
    item.due_at = due_at
    item.event_start_at = event_start_at
    item.event_end_at = event_end_at
    item.updated_at = datetime.utcnow()
    return item


def _hub_item_payload(item: HubItem, creator=None, assignee=None, reactions=None, comment_count: int = 0) -> dict:
    return {
        "id": str(item.id),
        "short_id": item.short_id,
        "type": item.item_type,
        "title": item.title,
        "body": item.body,
        "tags": item.tags or [],
        "status": item.status,
        "pinned_to_home": bool(item.pinned_to_home),
        "sent_to_chat_at": item.sent_to_chat_at.isoformat() if item.sent_to_chat_at else None,
        "chat_message_id": item.chat_message_id,
        "created_by_user_id": str(item.created_by_user_id) if item.created_by_user_id else None,
        "assigned_to_user_id": str(item.assigned_to_user_id) if item.assigned_to_user_id else None,
        "due_at": item.due_at.isoformat() if item.due_at else None,
        "event_start_at": item.event_start_at.isoformat() if item.event_start_at else None,
        "event_end_at": item.event_end_at.isoformat() if item.event_end_at else None,
        "source_type": item.source_type,
        "source_id": item.source_id,
        "cover_photo_id": item.cover_photo_id,
        "cover_photo_position_x": item.cover_photo_position_x if item.cover_photo_position_x is not None else 50,
        "cover_photo_position_y": item.cover_photo_position_y if item.cover_photo_position_y is not None else 50,
        "creator": creator,
        "assignee": assignee,
        "reactions": reactions or [],
        "comment_count": comment_count,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "archived_at": item.archived_at.isoformat() if item.archived_at else None,
    }


async def _load_hub_item_for_source(db: AsyncSession, item_type: str, source_id: int) -> HubItem | None:
    """Look up the existing HubItem mirror for a source row (idea/poll/reminder/event)."""
    result = await db.execute(
        select(HubItem).where(HubItem.source_type == item_type, HubItem.source_id == source_id)
    )
    return result.scalar_one_or_none()


async def _hub_item_metadata_for_sources(db: AsyncSession, item_type: str, source_ids: list[int], room_id=None) -> dict[int, dict]:
    if not source_ids:
        return {}
    stmt = (
        select(HubItem, User.id, User.username, User.nickname, User.role, User.avatar_url)
        .outerjoin(User, HubItem.created_by_user_id == User.id)
        .where(HubItem.source_type == item_type, HubItem.source_id.in_(source_ids))
    )
    if room_id is not None:
        stmt = stmt.where(HubItem.room_id == room_id)
    result = await db.execute(stmt)
    return {
        item.source_id: _hub_item_payload(
            item,
            creator=_user_payload_from_row(user_id, username, nickname, role, avatar_url),
        )
        for item, user_id, username, nickname, role, avatar_url in result.fetchall()
    }


def _event_creator_payload(user_id, username, nickname, role, metadata: dict | None) -> dict | None:
    creator = _user_payload_from_row(user_id, username, nickname, role)
    if creator:
        return creator
    if metadata:
        return metadata.get("creator")
    return None


def _apply_hub_metadata(payload: dict, metadata: dict | None) -> dict:
    if not metadata:
        return payload
    payload["hub_item"] = metadata
    payload["hub_item_id"] = metadata["id"]
    payload["short_id"] = metadata["short_id"]
    payload["tags"] = metadata["tags"]
    payload["pinned_to_home"] = metadata["pinned_to_home"]
    payload["cover_photo_position_x"] = metadata.get("cover_photo_position_x", 50)
    payload["cover_photo_position_y"] = metadata.get("cover_photo_position_y", 50)
    return payload


async def _hub_item_payloads(
    db: AsyncSession,
    group_id: int,
    *,
    item_type: str | None = None,
    pinned: bool | None = None,
    archived_only: bool = False,
    limit: int | None = None,
    room_id=None,
) -> list[dict]:
    stmt = (
        select(HubItem, User.id, User.username, User.nickname, User.role)
        .outerjoin(User, HubItem.created_by_user_id == User.id)
        .where(HubItem.group_id == group_id)
        .order_by(HubItem.pinned_to_home.desc(), desc(HubItem.updated_at))
    )
    if room_id is not None:
        stmt = stmt.where(HubItem.room_id == room_id)
    
    # Filter by archive status
    if archived_only:
        stmt = stmt.where(HubItem.status == HubItemStatus.archived.value)
    else:
        stmt = stmt.where(HubItem.status != HubItemStatus.archived.value)
    
    if item_type:
        stmt = stmt.where(HubItem.item_type == item_type)
    if pinned is not None:
        stmt = stmt.where(HubItem.pinned_to_home.is_(pinned))
    if limit:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).fetchall()
    payloads = []
    for item, user_id, username, nickname, role in rows:
        reactions = []
        comment_count = 0
        if item.source_type and item.source_id:
            reactions = (await _reaction_summary(db, item.source_type, [item.source_id])).get(item.source_id, [])
            comment_count = (await _comment_counts(db, item.source_type, [item.source_id])).get(item.source_id, 0)
        assignee = None
        if item.assigned_to_user_id:
            assignee_row = (
                await db.execute(select(User.id, User.username, User.nickname, User.role).where(User.id == item.assigned_to_user_id))
            ).first()
            if assignee_row:
                assignee = _user_payload_from_row(*assignee_row)
        payloads.append(_hub_item_payload(
            item,
            creator=_user_payload_from_row(user_id, username, nickname, role),
            assignee=assignee,
            reactions=reactions,
            comment_count=comment_count,
        ))
    return payloads


async def _hub_item_by_id_or_404(db: AsyncSession, group_id: int, item_id: str, room_id=None) -> HubItem:
    try:
        parsed_id = uuid.UUID(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Hub item not found") from exc
    item = await db.get(HubItem, parsed_id)
    if (
        not item
        or item.group_id != group_id
        or item.status == HubItemStatus.archived.value
        or (room_id is not None and item.room_id != room_id)
    ):
        raise HTTPException(status_code=404, detail="Hub item not found")
    return item


async def _event_by_id_or_404(db: AsyncSession, group_id: int, event_id: int, room_id=None) -> Event:
    event = await db.get(Event, event_id)
    if (
        not event
        or event.group_id != group_id
        or event.archived_at is not None
        or (room_id is not None and event.room_id != room_id)
    ):
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def _hub_item_chat_preview(item: HubItem, actor: User, assignee_name: str | None = None) -> str:
    lines = [f"{actor.nickname} shared {item.short_id}", "", item.title]
    if item.due_at:
        lines.append(f"Due {item.due_at.strftime('%d/%m/%Y, %H:%M')}")
    if item.event_start_at:
        lines.append(f"When {item.event_start_at.strftime('%d/%m/%Y, %H:%M')}")
    if assignee_name:
        lines.append(f"Assigned to {assignee_name}")
    if item.body and item.body != item.title:
        lines.append(item.body[:240])
    return "\n".join(lines)[:1000]


async def _log_activity(
    db: AsyncSession,
    *,
    group_id: int,
    actor_user_id,
    action: ActivityAction,
    target_type: str,
    target_id: int | None,
    summary: str,
):
    db.add(ActivityLog(
        group_id=group_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        summary=summary[:240],
    ))


def _serialize_for_history(val):
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    if hasattr(val, "value"):
        return val.value
    if isinstance(val, list):
        return [_serialize_for_history(v) for v in val]
    return val


async def _record_history(db: AsyncSession, item_type: str, item_id: int, user_id, before: dict, after: dict):
    changes = {}
    for field in before:
        old = _serialize_for_history(before[field])
        new = _serialize_for_history(after.get(field))
        if old != new:
            changes[field] = {"before": old, "after": new}
    if changes:
        db.add(ItemHistory(
            item_type=item_type,
            item_id=item_id,
            changed_by_user_id=user_id,
            changes=changes,
        ))


async def _reaction_summary(db: AsyncSession, target_type: str, ids: list[int]) -> dict[int, list[dict]]:
    if not ids:
        return {}
    result = await db.execute(
        select(Reaction.target_id, Reaction.emoji, func.count(Reaction.id))
        .where(Reaction.target_type == target_type, Reaction.target_id.in_(ids))
        .group_by(Reaction.target_id, Reaction.emoji)
    )
    summary: dict[int, list[dict]] = {item_id: [] for item_id in ids}
    for target_id, emoji, count in result.fetchall():
        summary.setdefault(target_id, []).append({"emoji": emoji, "count": count})
    return summary


async def _comment_counts(db: AsyncSession, target_type: str, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    result = await db.execute(
        select(Comment.target_id, func.count(Comment.id))
        .where(Comment.target_type == target_type, Comment.target_id.in_(ids))
        .group_by(Comment.target_id)
    )
    counts = {item_id: 0 for item_id in ids}
    counts.update({target_id: count for target_id, count in result.fetchall()})
    return counts


async def _bg_comment_notification(
    commenter_id, commenter_nickname: str,
    target_type: str, target_id: int,
    manager_ref,
):
    """Fire-and-forget: notify the owner of the commented-on item."""
    try:
        async with async_session_factory() as db:
            model_map = {"idea": Idea, "poll": Poll, "reminder": Reminder}
            model = model_map.get(target_type)
            if model and hasattr(model, "created_by_user_id"):
                result = await db.execute(
                    select(model.created_by_user_id).where(model.id == target_id)
                )
                owner_id = result.scalar_one_or_none()
            elif target_type == "event":
                result = await db.execute(
                    select(User.id)
                    .join(Event, User.session_id == Event.created_by_session_id)
                    .where(Event.id == target_id)
                )
                owner_id = result.scalar_one_or_none()
            else:
                return
            if not owner_id or owner_id == commenter_id:
                return
            title = f"{commenter_nickname} commented on your {target_type}"
            notif = Notification(user_id=owner_id, type="comment", title=title,
                                  target_type=target_type, target_id=target_id)
            db.add(notif)
            await db.flush()
            if manager_ref is not None:
                from app.domains.chat.events import OutgoingNotification
                await manager_ref.send_to_user_by_id(
                    str(owner_id),
                    OutgoingNotification(notification_id=notif.id, notif_type="comment",
                                         title=title, target_type=target_type, target_id=target_id).dict()
                )
            await db.commit()

            from app.domains.notifications.push_fanout import fanout_push_to_user
            await fanout_push_to_user(
                db,
                user_id=owner_id,
                notif_type="comment",
                title=title,
                url=_url_for_target(target_type, target_id),
                data={"target_type": target_type, "target_id": target_id, "notif_type": "comment"},
            )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("comment notification error: %s", exc)


def _url_for_target(target_type: str | None, target_id) -> str | None:
    """Map a notification target to the in-app route the SW should open."""
    if not target_type or target_id is None:
        return None
    routes = {
        "event": f"/events/{target_id}",
        "poll": "/polls",
        "idea": "/ideas",
        "reminder": "/reminders",
        "comment": "/items",
        "hub_item": f"/items?id={target_id}",
        "message": f"/chat?message={target_id}",
    }
    return routes.get(target_type, "/home")


async def _bg_broadcast_notification(
    creator_id, creator_nickname: str,
    notif_type: str, title: str,
    target_type: str, target_id: int,
    manager_ref,
    send_push: bool = True,
):
    """Fire-and-forget: notify all active members except the creator."""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(User.id).where(User.is_active.is_(True), User.id != creator_id)
            )
            member_ids = result.scalars().all()
            if not member_ids:
                return
            for uid in member_ids:
                db.add(Notification(user_id=uid, type=notif_type, title=title,
                                     target_type=target_type, target_id=target_id))
            await db.flush()
            if manager_ref is not None:
                from app.domains.chat.events import OutgoingNotification
                for uid in member_ids:
                    await manager_ref.send_to_user_by_id(
                        str(uid),
                        OutgoingNotification(notification_id=0, notif_type=notif_type,
                                              title=title, target_type=target_type, target_id=target_id).dict()
                    )
            await db.commit()

            if send_push:
                from app.domains.notifications.push_fanout import fanout_push_to_users
                await fanout_push_to_users(
                    db,
                    user_ids=member_ids,
                    notif_type=notif_type,
                    title=title,
                    url=_url_for_target(target_type, target_id),
                    data={"target_type": target_type, "target_id": target_id, "notif_type": notif_type},
                )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("broadcast notification error: %s", exc)


_POLL_PUSH_PREVIEW_MAX = 120


def _poll_push_preview(question: str) -> str:
    flat = " ".join(str(question or "").split())
    return flat if len(flat) <= _POLL_PUSH_PREVIEW_MAX else flat[: _POLL_PUSH_PREVIEW_MAX - 1] + "…"


async def _bg_poll_created_push_notification(
    creator_id,
    creator_nickname: str,
    group_id: int,
    poll_id: int,
    poll_question: str,
    hub_item_id=None,
):
    """Fire-and-forget: push a new-poll alert to active group members."""
    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(User.id)
                .join(GroupMember, User.session_id == GroupMember.user_session_id)
                .where(
                    GroupMember.group_id == group_id,
                    User.id != creator_id,
                    User.is_active.is_(True),
                    User.hidden_from_member_list.is_(False),
                    User.is_test_user.is_(False),
                    User.is_bot.is_(False),
                    User.status.notin_(["deactivated", "archived", "deleted"]),
                    User.user_type.notin_(["test", "system", "bot"]),
                )
            )
            member_ids = []
            seen = set()
            for uid in result.scalars().all():
                uid_str = str(uid)
                if uid_str in seen or uid_str == str(creator_id):
                    continue
                seen.add(uid_str)
                member_ids.append(uid)
            if not member_ids:
                return

            data = {
                "notif_type": "poll_created",
                "target_type": "poll",
                "target_id": poll_id,
            }
            if hub_item_id:
                data["hub_item_id"] = str(hub_item_id)

            from app.domains.notifications.push_fanout import fanout_push_to_user
            for uid in member_ids:
                await fanout_push_to_user(
                    db,
                    user_id=uid,
                    notif_type="poll_created",
                    title="New poll in Friend Hub",
                    body=f"{creator_nickname} created a poll: {_poll_push_preview(poll_question)}",
                    url=_url_for_target("poll", poll_id),
                    data=data,
                )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("poll-created push notification error: %s", exc)


# API Routes
@router.get("/health", response_model=HealthResponse)
async def health_check(manager: ConnectionManager = Depends(get_connection_manager)):
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        connections=manager.get_connection_count(),
        database="connected"
    )


@router.get("/server/resources")
async def get_server_resources(
    manager: ConnectionManager = Depends(get_connection_manager),
    db: AsyncSession = Depends(get_db_session),
):
    """VPS storage, database, AI usage, and live app stats."""
    import shutil
    from sqlalchemy import text as sa_text

    settings = get_settings()
    upload_path = get_photo_upload_path()

    # ── Disk ────────────────────────────────────────────────────────────────
    try:
        probe = upload_path if upload_path.exists() else upload_path.parent
        disk = shutil.disk_usage(probe)
        disk_total, disk_used, disk_free = disk.total, disk.used, disk.free
    except Exception:
        disk_total = disk_used = disk_free = 0

    # Upload directory size (photos + avatars)
    upload_bytes = 0
    try:
        for p in upload_path.parent.rglob("*"):
            if p.is_file():
                upload_bytes += p.stat().st_size
    except Exception:
        pass

    # ── Database ─────────────────────────────────────────────────────────────
    try:
        db_bytes = (await db.execute(
            sa_text("SELECT pg_database_size(current_database())")
        )).scalar_one() or 0
    except Exception:
        db_bytes = 0

    # ── App stats ────────────────────────────────────────────────────────────
    async def _count(stmt):
        return (await db.execute(stmt)).scalar_one() or 0

    users    = await _count(select(func.count(User.id)).where(User.is_active.is_(True)))
    messages = await _count(select(func.count(Message.id)).where(Message.is_deleted.is_(False)))
    photos   = await _count(select(func.count(Photo.id)))
    ideas    = await _count(select(func.count(Idea.id)))
    polls    = await _count(select(func.count(Poll.id)))

    # ── AI usage (current calendar month) ────────────────────────────────────
    try:
        ai_rows = (await db.execute(sa_text("""
            SELECT
                COALESCE(SUM(tokens_in), 0)  AS tokens_in,
                COALESCE(SUM(tokens_out), 0) AS tokens_out,
                COALESCE(SUM(cost_cents), 0) AS cost_cents
            FROM ai_usage_log
            WHERE created_at >= date_trunc('month', NOW())
        """))).first()
        ai_tokens_in  = int(ai_rows.tokens_in)
        ai_tokens_out = int(ai_rows.tokens_out)
        ai_cost_cents = int(ai_rows.cost_cents)
    except Exception:
        ai_tokens_in = ai_tokens_out = ai_cost_cents = 0

    return {
        "storage": {
            "disk_total_bytes":  disk_total,
            "disk_used_bytes":   disk_used,
            "disk_free_bytes":   disk_free,
            "upload_dir_bytes":  upload_bytes,
            "upload_warn_bytes": settings.photo_storage_warn_bytes,
            "upload_max_bytes":  settings.photo_storage_max_bytes,
        },
        "database": {
            "size_bytes": db_bytes,
        },
        "app": {
            "users":    users,
            "messages": messages,
            "photos":   photos,
            "ideas":    ideas,
            "polls":    polls,
            "connections": manager.get_connection_count() if manager else 0,
        },
        "ai": {
            "provider":         settings.ai_api_provider,
            "configured":       bool(settings.ai_api_key),
            "budget_cents":     settings.ai_monthly_budget_cents,
            "used_cents":       ai_cost_cents,
            "tokens_in":        ai_tokens_in,
            "tokens_out":       ai_tokens_out,
            "tokens_total":     ai_tokens_in + ai_tokens_out,
        },
    }

@router.post("/session", response_model=SessionResponse)
async def create_session(request: SessionRequest):
    """Create a new chat session with a nickname."""
    session_id = str(uuid.uuid4())
    
    return SessionResponse(
        session_id=session_id,
        nickname=request.nickname,
        status="created"
    )

@router.post("/auth/register", response_model=AuthResponse)
async def register_user(
    request: AuthRegisterRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    raise HTTPException(status_code=403, detail="Public signup is disabled")


@router.post("/auth/demo-session", response_model=AuthResponse)
async def create_demo_session(
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
):
    """Create a temporary guest identity restricted to the public demo room."""
    from app.domains.demo.service import allow_demo_session_request

    ip_address = http_request.client.host if http_request.client else "unknown"
    if not allow_demo_session_request(ip_address):
        raise HTTPException(status_code=429, detail="Demo session limit reached. Please try again later.")

    user, token, error = await AuthService(db).create_demo_guest(
        user_agent=http_request.headers.get("user-agent"),
        ip_address=ip_address,
    )
    if error or not user or not token:
        raise HTTPException(status_code=503, detail=error or "Demo is unavailable")
    _set_auth_cookie(response, token, session_only=True)
    return AuthResponse(user=AuthUserResponse(**user_payload(user)), token=None)


@router.post("/auth/claim-invite", response_model=AuthResponse)
async def claim_invite(
    request: ClaimInviteRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
):
    auth_service = AuthService(db)
    user, token, error = await auth_service.claim_invite(
        invite_code=request.invite_code,
        pin=request.pin,
        pin_confirm=request.pin_confirm,
        user_agent=http_request.headers.get("user-agent"),
        ip_address=http_request.client.host if http_request.client else None,
    )
    if error or not user or not token:
        raise HTTPException(status_code=400, detail=error or "Invite claim failed")
    _set_auth_cookie(response, token)
    return AuthResponse(user=AuthUserResponse(**user_payload(user)), token=None)


@router.get("/auth/invite/{invite_code}")
async def peek_invite(
    invite_code: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Validate an invite code for the /join landing page without consuming it."""
    invite, error = await AuthService(db).peek_invite(invite_code)
    if error:
        return {"valid": False, "display_name": None, "room": None}
    return {
        "valid": True,
        "display_name": invite.get("display_name") if invite else None,
        "room": invite.get("room") if invite else None,
    }


@router.post("/auth/pin-login", response_model=AuthResponse)
async def pin_login(
    request: PinLoginRequest,
    http_request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
):
    auth_service = AuthService(db)
    user, token, error = await auth_service.pin_login(
        username=request.username,
        pin=request.pin,
        user_agent=http_request.headers.get("user-agent"),
        ip_address=http_request.client.host if http_request.client else None,
    )
    if error or not user or not token:
        raise HTTPException(status_code=400, detail=error or AuthService.GENERIC_LOGIN_ERROR)
    _set_auth_cookie(response, token)
    return AuthResponse(user=AuthUserResponse(**user_payload(user)), token=None)

@router.get("/auth/me", response_model=AuthResponse)
async def get_current_user(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    auth_service = AuthService(db)
    user, _ = await _authenticate_request(auth_service, authorization, session_cookie)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return AuthResponse(user=AuthUserResponse(**user_payload(user)), token=None)

@router.post("/auth/logout")
async def logout_user(
    response: Response = None,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    auth_service = AuthService(db)
    if not await auth_service.logout(_auth_token(authorization, session_cookie)):
        raise HTTPException(status_code=401, detail="Authentication required")
    if response is not None:
        _clear_auth_cookie(response)
    return {"status": "logged_out"}


@router.get("/admin/archive")
async def admin_get_archive(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    group = await _default_group(db)
    items = await _hub_item_payloads(db, group.id, archived_only=True)

    photo_rows = (await db.execute(
        select(Photo, User.nickname)
        .outerjoin(User, Photo.uploaded_by_session_id == User.session_id)
        .where(Photo.deleted_at.is_not(None))
        .order_by(desc(Photo.deleted_at))
    )).fetchall()
    photos = [_photo_payload(photo, nickname=nickname) for photo, nickname in photo_rows]

    return {"items": items, "total": len(items), "photos": photos, "photos_total": len(photos)}


@router.post("/admin/users")
async def admin_create_user(
    http_request: Request,
    request: AdminUserCreateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user, invite_code, error = await AuthService(db).create_admin_user(
        username=request.username,
        display_name=request.display_name,
        role=request.role,
    )
    if error or not user or not invite_code:
        raise HTTPException(status_code=400, detail=error or "User creation failed")

    if request.room_ids:
        role = _clean_room_member_role(request.room_role, username=user.username)
        valid_room_ids = set((await db.execute(
            select(Room.id).where(Room.id.in_(request.room_ids))
        )).scalars().all())
        for room_id in request.room_ids:
            if room_id not in valid_room_ids:
                continue
            await db.execute(
                insert(RoomMembership).values(
                    room_id=room_id,
                    user_id=user.id,
                    role=role,
                    joined_at=datetime.utcnow(),
                ).on_conflict_do_update(
                    index_elements=["room_id", "user_id"],
                    set_={"role": role},
                )
            )
        await db.commit()
        await db.refresh(user)

    return {
        "user": await _admin_user_response(db, user),
        "invite_code": invite_code,
        "invite_url": _invite_url(invite_code, http_request),
    }


@router.get("/admin/users")
async def admin_list_users(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    users = await AuthService(db).repository.list_users()
    rooms_by_user, rooms = await _admin_user_room_payloads(db, users)
    return {
        "users": [
            {
                **admin_user_payload(user),
                "rooms": rooms_by_user.get(str(user.id), []),
            }
            for user in users
        ],
        "rooms": rooms,
    }


@router.post("/admin/users/{user_id}/reset-pin")
async def admin_reset_pin(
    user_id: uuid.UUID,
    request: Request,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user, invite_code, error = await AuthService(db).reset_pin(user_id)
    if error or not user or not invite_code:
        raise HTTPException(status_code=400, detail=error or "PIN reset failed")
    return {
        "user": await _admin_user_response(db, user),
        "invite_code": invite_code,
        "invite_url": _invite_url(invite_code, request),
    }


@router.post("/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(
    user_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user, error = await AuthService(db).deactivate_user(user_id)
    if error or not user:
        raise HTTPException(status_code=400, detail=error or "Deactivate failed")
    return {"user": await _admin_user_response(db, user)}


@router.post("/admin/users/{user_id}/reactivate")
async def admin_reactivate_user(
    user_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user, error = await AuthService(db).reactivate_user(user_id)
    if error or not user:
        raise HTTPException(status_code=400, detail=error or "Reactivate failed")
    return {"user": await _admin_user_response(db, user)}


@router.patch("/admin/users/{user_id}/role")
async def admin_update_user_role(
    user_id: uuid.UUID,
    request: AdminRoleUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user, error = await AuthService(db).update_role(user_id, request.role)
    if error or not user:
        raise HTTPException(status_code=400, detail=error or "Role update failed")
    return {"user": await _admin_user_response(db, user)}


@router.patch("/admin/users/{user_id}/profile")
async def admin_update_user_profile(
    user_id: uuid.UUID,
    request: AdminUserProfileUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if request.username is not None:
        username = request.username.strip().lower()
        error = AuthService._validate_username(username)
        if error:
            raise HTTPException(status_code=400, detail=error)
        role = user.role.value if hasattr(user.role, "value") else user.role
        if role == "owner" and username != "techlett":
            raise HTTPException(status_code=400, detail="The platform owner username must stay techlett")
        existing = (await db.execute(
            select(User).where(func.lower(User.username) == username, User.id != user.id)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=400, detail="Username is already taken")
        user.username = username
        user.updated_at = datetime.utcnow()

    await db.commit()
    await db.refresh(user)
    return {"user": await _admin_user_response(db, user)}


@router.patch("/admin/users/{user_id}/rooms/{room_id}")
async def admin_update_user_room(
    user_id: uuid.UUID,
    room_id: uuid.UUID,
    request: AdminUserRoomUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    room = (await db.execute(select(Room).where(Room.id == room_id))).scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    role = _clean_room_member_role(request.role, username=user.username)
    stmt = insert(RoomMembership).values(
        room_id=room.id,
        user_id=user.id,
        role=role,
        joined_at=datetime.utcnow(),
    ).on_conflict_do_update(
        index_elements=["room_id", "user_id"],
        set_={"role": role},
    )
    await db.execute(stmt)
    await db.commit()
    await db.refresh(user)
    return {"user": await _admin_user_response(db, user)}


@router.delete("/admin/users/{user_id}/rooms/{room_id}")
async def admin_remove_user_room(
    user_id: uuid.UUID,
    room_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.execute(
        delete(RoomMembership)
        .where(RoomMembership.user_id == user.id)
        .where(RoomMembership.room_id == room_id)
    )
    await db.commit()
    await db.refresh(user)
    return {"user": await _admin_user_response(db, user)}


@router.get("/admin/identity/imported-identities")
async def admin_list_imported_identities(
    status: str | None = None,
    source: str | None = None,
    search: str | None = None,
    linked_user_id: uuid.UUID | None = None,
    limit: int = 100,
    offset: int = 0,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    identities = await IdentityService(db).list_imported_identities(
        status=status,
        source=source,
        search=search,
        linked_user_id=linked_user_id,
        limit=limit,
        offset=offset,
    )
    return {
        "imported_identities": [_imported_identity_payload(identity) for identity in identities],
        "total": len(identities),
        "limit": limit,
        "offset": offset,
    }


@router.post("/admin/identity/imported-identities")
async def admin_create_imported_identity(
    request: ImportedIdentityCreate,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    identity, error = await IdentityService(db).create_imported_identity(request)
    if error or not identity:
        raise HTTPException(status_code=400, detail=error or "Imported identity creation failed")
    return {"imported_identity": _imported_identity_payload(identity)}


@router.patch("/admin/identity/imported-identities/{identity_id}")
async def admin_update_imported_identity(
    identity_id: uuid.UUID,
    request: ImportedIdentityUpdate,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    identity, error = await IdentityService(db).update_imported_identity(identity_id, request)
    if error or not identity:
        status_code = 404 if error == "Imported identity not found" else 400
        raise HTTPException(status_code=status_code, detail=error or "Imported identity update failed")
    return {"imported_identity": _imported_identity_payload(identity)}


@router.post("/admin/identity/imported-identities/{identity_id}/link")
async def admin_link_imported_identity(
    identity_id: uuid.UUID,
    request: ImportedIdentityLinkRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    identity, error = await IdentityService(db).link_imported_identity(identity_id, request.user_id)
    if error or not identity:
        status_code = 404 if error == "Imported identity not found" else 400
        raise HTTPException(status_code=status_code, detail=error or "Imported identity link failed")
    return {"imported_identity": _imported_identity_payload(identity)}


@router.post("/admin/identity/imported-identities/{identity_id}/unlink")
async def admin_unlink_imported_identity(
    identity_id: uuid.UUID,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    identity, error = await IdentityService(db).unlink_imported_identity(identity_id)
    if error or not identity:
        raise HTTPException(status_code=404, detail=error or "Imported identity unlink failed")
    return {"imported_identity": _imported_identity_payload(identity)}


@router.get("/admin/identity/users")
async def admin_list_identity_users(
    status: str | None = None,
    user_type: str | None = None,
    search: str | None = None,
    likely_test_user: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    users = await IdentityService(db).list_users_for_cleanup(
        status=status,
        user_type=user_type,
        search=search,
        likely_test_user=likely_test_user,
        limit=limit,
        offset=offset,
    )
    return {"users": [_identity_user_payload(item) for item in users], "total": len(users), "limit": limit, "offset": offset}


@router.patch("/admin/identity/users/{user_id}")
async def admin_update_identity_user(
    user_id: uuid.UUID,
    request: UserCleanupUpdate,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_owner_user_or_403(authorization, db, session_cookie)
    user, error = await IdentityService(db).update_user_cleanup(user_id, request)
    if error or not user:
        status_code = 404 if error == "User not found" else 400
        raise HTTPException(status_code=status_code, detail=error or "User cleanup update failed")
    return {"user": _identity_user_payload({"user": user, "message_count": 0})}

@router.patch("/users/me", response_model=AuthResponse)
async def update_current_user(
    request: ProfileUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    auth_service = AuthService(db)
    user, error = await auth_service.update_nickname(_auth_token(authorization, session_cookie), request.nickname)
    if error or not user:
        status_code = 401 if error == "Authentication required" else 400
        raise HTTPException(status_code=status_code, detail=error or "Profile update failed")
    return AuthResponse(user=AuthUserResponse(**user_payload(user)), token=None)


@router.post("/users/me/avatar")
async def upload_user_avatar(
    request: AvatarUploadRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    user = await _current_user_or_401(authorization, db, session_cookie)
    data_url = request.data_url.strip()
    if not data_url.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported")
    try:
        _header, encoded = data_url.split(",", 1)
        image_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid image data") from exc
    if len(image_bytes) > settings.photo_max_upload_bytes:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")

    processed = process_photo_upload(
        image_bytes,
        display_max_width=512,
        thumbnail_max_width=512,
        jpeg_quality=settings.photo_jpeg_quality,
    )

    avatar_dir = get_photo_upload_path().parent / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{user.id}.jpg"
    (avatar_dir / filename).write_bytes(processed.display_bytes)

    avatar_url = f"/uploads/avatars/{filename}"
    await db.execute(
        update(User).where(User.id == user.id).values(avatar_url=avatar_url)
    )
    await db.commit()
    return {"avatar_url": avatar_url}


@router.delete("/users/me/avatar")
async def delete_user_avatar(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    if user.avatar_url:
        avatar_dir = get_photo_upload_path().parent / "avatars"
        filepath = avatar_dir / f"{user.id}.jpg"
        filepath.unlink(missing_ok=True)
    await db.execute(
        update(User).where(User.id == user.id).values(avatar_url=None)
    )
    await db.commit()
    return {"status": "deleted"}


@router.get("/messages", response_model=MessagesResponse)
async def get_messages(
    limit: int = 50, 
    offset: int = 0, 
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session)
):
    """Get message history."""
    chat_service = ChatService(db)
    start_at = _to_utc_naive(start_at) if start_at else None
    end_at = _to_utc_naive(end_at) if end_at else None
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    messages = await chat_service.get_recent_messages(
        limit=limit,
        offset=offset,
        start_at=start_at,
        end_at=end_at,
        room_id=room_id,
    )
    
    return MessagesResponse(
        messages=messages,
        total=len(messages),
        limit=limit,
        offset=offset
    )

@router.get("/messages/{message_id}/context", response_model=MessagesResponse)
async def get_message_context(
    message_id: int,
    before: int = 25,
    after: int = 25,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Get a small chronological message window around one message."""
    before = max(0, min(before, 100))
    after = max(0, min(after, 100))
    chat_service = ChatService(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    messages = await chat_service.message_service.get_message_context(
        message_id,
        before=before,
        after=after,
        room_id=room_id,
    )
    if not messages:
        raise HTTPException(status_code=404, detail="Message not found")
    return MessagesResponse(
        messages=messages,
        total=len(messages),
        limit=before + after + 1,
        offset=0,
    )


async def _set_message_pinned(
    message_id: int,
    pinned: bool,
    *,
    authorization: str | None,
    session_cookie: str | None,
    x_room_slug: str | None,
    db: AsyncSession,
):
    """Pin/unpin a chat message. Admins and owners only."""
    user = await _current_user_or_401(authorization, db, session_cookie)
    _ensure_not_demo_guest(user)
    if not _is_admin_user(user):
        raise HTTPException(status_code=403, detail="Only admins can pin messages")
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    message = await db.get(Message, message_id)
    if not message or message.room_id != room_id or message.is_deleted:
        raise HTTPException(status_code=404, detail="Message not found")

    message.is_pinned = pinned
    message.pinned_at = datetime.utcnow() if pinned else None
    message.pinned_by_session_id = user.session_id if pinned else None
    await db.commit()
    return {"message_id": message_id, "is_pinned": pinned}


@router.post("/messages/{message_id}/pin")
async def pin_message(
    message_id: int,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    return await _set_message_pinned(
        message_id, True,
        authorization=authorization, session_cookie=session_cookie,
        x_room_slug=x_room_slug, db=db,
    )


@router.delete("/messages/{message_id}/pin")
async def unpin_message(
    message_id: int,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    return await _set_message_pinned(
        message_id, False,
        authorization=authorization, session_cookie=session_cookie,
        x_room_slug=x_room_slug, db=db,
    )


async def _read_state_user_and_room(
    db: AsyncSession,
    authorization: str | None,
    session_cookie: str | None,
    x_room_slug: str | None,
):
    from app.domains.rooms.service import RoomService

    user = await _current_user_or_401(authorization, db, session_cookie)
    room, error = await RoomService(db).resolve_room(slug=x_room_slug, user_id=user.id)
    if error:
        if "not found" in error or "not a member" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)
    return user, room.id


@router.put("/chat/read-state")
async def update_chat_read_state(
    payload: ReadStateUpdate,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Record the newest message the user has read in the current room."""
    from app.domains.chat.read_state_repository import ChatReadStateRepository
    from app.domains.messages.repository import MessageRepository

    user, room_id = await _read_state_user_and_room(db, authorization, session_cookie, x_room_slug)
    message = await MessageRepository(db).get_message_by_id(payload.message_id, room_id=room_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found in this room")
    state = await ChatReadStateRepository(db).upsert_forward(user.id, room_id, payload.message_id)
    await db.commit()
    return {
        "last_read_message_id": state.last_read_message_id,
        "updated_at": state.updated_at.isoformat(),
    }


@router.get("/chat/read-state")
async def get_chat_read_state(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Return the user's read state and unread count for the current room."""
    from app.domains.chat.read_state_repository import ChatReadStateRepository

    user, room_id = await _read_state_user_and_room(db, authorization, session_cookie, x_room_slug)
    repo = ChatReadStateRepository(db)
    state = await repo.get(user.id, room_id)
    last_read_id = state.last_read_message_id if state else None
    unread = await repo.count_messages_after(room_id, last_read_id)
    return {"last_read_message_id": last_read_id, "unread_count": unread}


@router.get("/members", response_model=MembersResponse)
async def get_members(
    include_bots: bool = False,
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
):
    """Get group members with roles and live online status, optionally filtered by room."""
    user = await _current_user_or_401(authorization, db, session_cookie)
    if getattr(user, "user_type", None) == "guest" and x_room_slug not in (None, "demo"):
        raise HTTPException(status_code=403, detail="Guest sessions are restricted to the demo room")
    room_id = None
    if x_room_slug:
        from sqlalchemy import select as _select
        room_row = await db.execute(_select(Room.id).where(Room.slug == x_room_slug))
        room_id = room_row.scalar_one_or_none()

    member_service = MemberService(db)
    members = await member_service.get_members(include_bots=include_bots, room_id=room_id)
    unlinked_imported_members = await member_service.get_unlinked_imported_members(room_id=room_id)

    if manager is not None:
        live_sids = {u["session_id"] for u in manager.get_online_users(room_id)}
        for member in members:
            member["is_online"] = member["session_id"] in live_sids

    return MembersResponse(
        members=members,
        total=len(members),
        unlinked_imported_members=unlinked_imported_members,
    )

@router.get("/members/lookup")
async def get_member_by_username(
    username: str,
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """Fetch a single member profile by username."""
    member_service = MemberService(db)
    members = await member_service.get_members(include_bots=True)
    member = next(
        (m for m in members if (m.get("username") or "").lower() == username.lower()),
        None,
    )
    if not member:
        raise HTTPException(status_code=404, detail="Member not found")
    if manager is not None:
        live_sids = {u["session_id"] for u in manager.get_online_users()}
        member["is_online"] = member["session_id"] in live_sids
    return {"member": member}


async def _profile_user_and_linked_identity_ids(db: AsyncSession, username: str) -> tuple[User, list[uuid.UUID]]:
    user_result = await db.execute(
        select(User).where(func.lower(User.username) == username.lower())
    )
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Member not found")

    linked_result = await db.execute(
        select(ImportedIdentity.id).where(ImportedIdentity.linked_user_id == user.id)
    )
    return user, list(linked_result.scalars().all())


@router.get("/members/{username}/profile-summary")
async def get_member_profile_summary(
    username: str,
    db: AsyncSession = Depends(get_db_session),
):
    user, linked_identity_ids = await _profile_user_and_linked_identity_ids(db, username)

    linked_result = await db.execute(
        select(ImportedIdentity)
        .where(ImportedIdentity.linked_user_id == user.id)
        .order_by(desc(ImportedIdentity.message_count), ImportedIdentity.source_display_name.asc())
    )
    linked_identities = linked_result.scalars().all()
    linked_identity_message_count = sum(identity.message_count or 0 for identity in linked_identities)

    current_filter = and_(
        Message.is_imported.is_(False),
        or_(
            Message.user_id == user.id,
            and_(Message.user_id.is_(None), Message.user_session_id == user.session_id),
        ),
    )
    current_count_result = await db.execute(
        select(func.count(Message.id)).where(current_filter)
    )
    current_message_count = current_count_result.scalar_one() or 0

    imported_message_count = 0
    if linked_identity_ids:
        imported_count_result = await db.execute(
            select(func.count(func.distinct(Message.id))).where(
                Message.imported_identity_id.in_(linked_identity_ids)
            )
        )
        imported_message_count = imported_count_result.scalar_one() or 0
    if imported_message_count == 0:
        imported_message_count = linked_identity_message_count

    return {
        "summary": {
            "current_message_count": current_message_count,
            "imported_message_count": imported_message_count,
            "total_message_count": current_message_count + imported_message_count,
            "linked_imported_identities": [
                {
                    "id": str(identity.id),
                    "source": identity.source,
                    "source_display_name": identity.source_display_name,
                    "message_count": identity.message_count or 0,
                    "first_seen_at": identity.first_seen_at.isoformat() if identity.first_seen_at else None,
                    "last_seen_at": identity.last_seen_at.isoformat() if identity.last_seen_at else None,
                }
                for identity in linked_identities
            ],
        }
    }


@router.get("/members/{username}/photos")
async def get_member_photos(
    username: str,
    limit: int = 60,
    db: AsyncSession = Depends(get_db_session),
):
    user, linked_identity_ids = await _profile_user_and_linked_identity_ids(db, username)

    conditions = [
        and_(
            Photo.uploaded_by_session_id == user.session_id,
            or_(Photo.source_type.is_(None), Photo.source_type != "messenger_import"),
        )
    ]
    if linked_identity_ids:
        conditions.append(Message.imported_identity_id.in_(linked_identity_ids))

    LinkedIdentity = aliased(ImportedIdentity)
    LinkedUser = aliased(User)
    result = await db.execute(
        select(Photo, User.nickname, Message.id, LinkedUser.nickname, LinkedUser.session_id)
        .outerjoin(User, Photo.uploaded_by_session_id == User.session_id)
        .outerjoin(Message, Photo.message_id == Message.id)
        .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
        .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
        .where(Photo.deleted_at.is_(None), or_(*conditions))
        .order_by(desc(Photo.created_at))
        .limit(max(1, min(limit, 120)))
    )
    photos = [
        _photo_payload(
            photo,
            nickname=linked_nickname or nickname,
            message_id=message_id,
            uploaded_by_session_id=linked_session_id or photo.uploaded_by_session_id,
        )
        for photo, nickname, message_id, linked_nickname, linked_session_id in result.fetchall()
    ]
    return {"photos": photos, "total": len(photos)}


@router.get("/members/{username}/messages", response_model=MessagesResponse)
async def get_member_messages(
    username: str,
    limit: int = 20,
    offset: int = 0,
    source: str = "all",
    db: AsyncSession = Depends(get_db_session),
):
    user, linked_identity_ids = await _profile_user_and_linked_identity_ids(db, username)
    if source not in {"all", "current", "imported"}:
        raise HTTPException(status_code=400, detail="source must be all, current, or imported")

    message_service = MessageService(db)
    messages = await message_service.get_messages_by_user(
        session_id=str(user.session_id),
        limit=limit,
        offset=offset,
        imported_identity_ids=linked_identity_ids,
        source=source,
    )
    return MessagesResponse(messages=messages, total=len(messages), limit=limit, offset=offset)


@router.get("/members/{username}/activity")
async def get_member_activity(
    username: str,
    db: AsyncSession = Depends(get_db_session),
):
    """Fetch recent activity for a member by username."""
    user, linked_identity_ids = await _profile_user_and_linked_identity_ids(db, username)

    activity_result = await db.execute(
        select(ActivityLog)
        .where(ActivityLog.actor_user_id == user.id)
        .order_by(desc(ActivityLog.created_at))
        .limit(20)
    )
    items = [
        {
            "id": f"activity-{item.id}",
            "action": item.action.value if hasattr(item.action, "value") else item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "summary": item.summary,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        for item in activity_result.scalars().all()
    ]

    linked_identity_result = await db.execute(
        select(ImportedIdentity)
        .where(ImportedIdentity.linked_user_id == user.id)
        .order_by(desc(ImportedIdentity.message_count), ImportedIdentity.source_display_name.asc())
    )
    linked_identities = linked_identity_result.scalars().all()

    if linked_identity_ids:
        imported_message_result = await db.execute(
            select(Message)
            .where(
                Message.imported_identity_id.in_(linked_identity_ids),
                Message.is_deleted.is_(False),
            )
            .order_by(desc(Message.created_at))
            .limit(20)
        )
        for message in imported_message_result.scalars().all():
            content = (message.content or "").strip()
            summary = content.splitlines()[0] if content else "Imported Messenger message"
            items.append({
                "id": f"message-{message.id}",
                "action": "created",
                "target_type": "message",
                "target_id": message.id,
                "summary": summary[:240],
                "created_at": message.created_at.isoformat() if message.created_at else None,
            })

    if not any(item["target_type"] == "message" for item in items):
        for identity in linked_identities:
            if not identity.message_count:
                continue
            items.append({
                "id": f"imported-identity-{identity.id}",
                "action": "created",
                "target_type": "message",
                "target_id": None,
                "summary": f"Linked Messenger archive for {identity.source_display_name}: {identity.message_count:,} imported messages",
                "created_at": identity.last_seen_at.isoformat() if identity.last_seen_at else identity.updated_at.isoformat() if identity.updated_at else None,
            })

    items.sort(key=lambda item: item["created_at"] or "", reverse=True)
    items = items[:20]
    return {
        "activity": items
    }


@router.patch("/members/{session_id}/role")
async def update_member_role(
    session_id: str,
    request: RoleUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    auth_service = AuthService(db)
    requester, _ = await _authenticate_request(auth_service, authorization, session_cookie)
    if not requester:
        raise HTTPException(status_code=401, detail="Authentication required")

    member_service = MemberService(db)
    updated = await member_service.assign_role(session_id, request.role, str(requester.session_id))
    if not updated:
        raise HTTPException(status_code=403, detail="Not allowed to assign that role")
    return {"status": "updated"}


@router.get("/members/{session_id}/profile")
async def get_member_profile(
    session_id: str,
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """Read member profile metadata (nickname, display_role, bio, avatar_emoji)."""
    member_service = MemberService(db)
    profile = await member_service.get_profile(session_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Member not found")
    if manager is not None:
        live_sids = {u["session_id"] for u in manager.get_online_users()}
        profile["is_online"] = profile["session_id"] in live_sids
    return {"profile": profile}


@router.patch("/members/{session_id}/profile")
async def update_member_profile(
    session_id: str,
    request: ProfileMetadataUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Update member profile metadata. Permissions follow NicknameChangePolicy
    (Phase 1 default: self-edit, with admin/owner override)."""
    from app.domains.members.profile import ProfileError, ProfileUpdate

    requester = await _current_user_or_401(authorization, db, session_cookie)

    update_in = ProfileUpdate(
        nickname=request.nickname,
        display_role=request.display_role,
        bio=request.bio,
        avatar_emoji=request.avatar_emoji,
    )
    member_service = MemberService(db)
    try:
        profile = await member_service.update_profile(
            target_session_id=session_id,
            update_in=update_in,
            requester_session_id=str(requester.session_id),
        )
    except ProfileError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return {"profile": profile}


@router.get("/hub-items")
async def get_hub_items(
    type: str | None = None,
    pinned: bool | None = None,
    limit: int | None = None,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    item_type = type.strip().lower() if type else None
    if item_type and item_type not in {item.value for item in HubItemType}:
        raise HTTPException(status_code=400, detail="Invalid hub item type")
    items = await _hub_item_payloads(
        db,
        group.id,
        item_type=item_type,
        pinned=pinned,
        limit=limit,
        room_id=room_id,
    )
    return {"items": items, "total": len(items)}


@router.post("/hub-items")
async def create_hub_item(
    request: HubItemCreateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    item_type = request.type.strip().lower()
    if item_type not in {item.value for item in HubItemType}:
        raise HTTPException(status_code=400, detail="Invalid hub item type")
    sequence = await _next_hub_item_sequence(db, item_type, room_id=room_id)
    item = HubItem(
        group_id=group.id,
        room_id=room_id,
        item_type=item_type,
        type_sequence=sequence,
        short_id=f"#{HUB_ITEM_PREFIXES[item_type]}-{sequence}",
        title=_clean_text(request.title, field="Title", max_length=220),
        body=_optional_text(request.body, max_length=2000),
        tags=_clean_tags(request.tags),
        status=HubItemStatus.open.value,
        created_by_user_id=user.id,
        assigned_to_user_id=request.assigned_to_user_id,
        due_at=_to_utc_naive(request.due_at) if request.due_at else None,
        event_start_at=_to_utc_naive(request.event_start_at) if request.event_start_at else None,
        event_end_at=_to_utc_naive(request.event_end_at) if request.event_end_at else None,
    )
    db.add(item)
    await db.flush()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="hub_item", target_id=None, summary=f"{user.nickname} created {item.short_id}: {item.title}")
    await db.commit()
    await db.refresh(item)
    return {"item": _hub_item_payload(item, creator=user_payload(user))}


@router.patch("/hub-items/{item_id}")
async def update_hub_item(
    item_id: str,
    request: HubItemUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    item = await _hub_item_by_id_or_404(db, group.id, item_id, room_id=room_id)
    if item.source_type == "event" and item.source_id:
        event = await db.get(Event, item.source_id)
        if event:
            _require_event_editor(user, event)
    elif not _can_manage_creator_owned_item(user, item.created_by_user_id):
        # Pinning/status flips still get to flow through the dedicated pin
        # endpoint; this PATCH is for content edits and requires creator/admin.
        if any(_field_was_set(request, f) for f in ("title", "body", "tags", "short_id")):
            raise HTTPException(status_code=403, detail="Only the creator or an admin can edit this item")

    before = {
        "title": item.title,
        "body": item.body,
        "tags": list(item.tags or []),
        "short_id": item.short_id,
    }

    if request.title is not None:
        item.title = _clean_text(request.title, field="Title", max_length=220)
    if request.body is not None:
        item.body = _optional_text(request.body, max_length=2000)
    if request.tags is not None:
        item.tags = _clean_tags(request.tags)
    if request.short_id is not None:
        normalised = _clean_short_id(request.short_id)
        if normalised.upper() != (item.short_id or "").upper():
            await _ensure_short_id_unique(db, group.id, normalised, item.id, room_id=room_id)
        item.short_id = normalised
    if request.status is not None:
        status = request.status.strip().lower()
        if status not in {item.value for item in HubItemStatus}:
            raise HTTPException(status_code=400, detail="Invalid hub item status")
        item.status = status
    if request.pinned_to_home is not None:
        item.pinned_to_home = bool(request.pinned_to_home)
    if _field_was_set(request, "assigned_to_user_id"):
        item.assigned_to_user_id = request.assigned_to_user_id
    if _field_was_set(request, "due_at"):
        item.due_at = _to_utc_naive(request.due_at) if request.due_at else None
    if _field_was_set(request, "event_start_at"):
        item.event_start_at = _to_utc_naive(request.event_start_at) if request.event_start_at else None
    if _field_was_set(request, "event_end_at"):
        item.event_end_at = _to_utc_naive(request.event_end_at) if request.event_end_at else None
    item.updated_at = datetime.utcnow()

    after = {
        "title": item.title,
        "body": item.body,
        "tags": list(item.tags or []),
        "short_id": item.short_id,
    }
    if item.source_type and item.source_id:
        await _record_history(db, item.source_type, item.source_id, user.id, before, after)
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="hub_item", target_id=None, summary=f"{user.nickname} updated {item.short_id}")
    await db.commit()
    return {"item": _hub_item_payload(item)}


@router.post("/hub-items/{item_id}/pin")
async def pin_hub_item(
    item_id: str,
    request: HubItemPinRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    item = await _hub_item_by_id_or_404(db, group.id, item_id, room_id=room_id)
    item.pinned_to_home = bool(request.pinned)
    item.updated_at = datetime.utcnow()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="hub_item", target_id=None, summary=f"{user.nickname} {'pinned' if item.pinned_to_home else 'unpinned'} {item.short_id}")
    await db.commit()
    return {"item": _hub_item_payload(item)}


@router.post("/hub-items/{item_id}/send-to-chat")
async def send_hub_item_to_chat(
    item_id: str,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    item = await _hub_item_by_id_or_404(db, group.id, item_id, room_id=room_id)
    assignee_name = None
    if item.assigned_to_user_id:
        assignee_name = (await db.execute(select(User.nickname).where(User.id == item.assigned_to_user_id))).scalar_one_or_none()
    message = Message(
        user_session_id=user.session_id,
        user_id=user.id,
        content=_hub_item_chat_preview(item, user, assignee_name),
        hub_item_id=item.id,
        room_id=room_id,
    )
    db.add(message)
    await db.flush()
    item.sent_to_chat_at = datetime.utcnow()
    item.chat_message_id = message.id
    item.updated_at = datetime.utcnow()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="message", target_id=message.id, summary=f"{user.nickname} shared {item.short_id} to chat")
    await db.commit()
    return {"status": "sent", "message_id": message.id, "item": _hub_item_payload(item)}


@router.get("/hub-items/references/parse")
async def parse_hub_item_references(text: str):
    return {"references": find_hub_item_references(text)}


@router.get("/hub-items/by-short-id")
async def get_hub_item_by_short_id(
    ref: str,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Fetch a hub item by its short_id reference.
    Pass ref without the # prefix, e.g. ref=P-1 for #P-1.
    """
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    short_id = ref if ref.startswith("#") else f"#{ref}"
    result = await db.execute(
        select(HubItem).where(
            HubItem.group_id == group.id,
            func.upper(HubItem.short_id) == short_id.upper(),
            HubItem.room_id == room_id,
            HubItem.status != HubItemStatus.archived.value,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Hub item not found")
    creator = None
    if item.created_by_user_id:
        row = (await db.execute(
            select(User.id, User.username, User.nickname, User.role)
            .where(User.id == item.created_by_user_id)
        )).first()
        if row:
            creator = _user_payload_from_row(*row)
    payload = _hub_item_payload(item, creator=creator)
    if item.source_type == "reminder" and item.source_id:
        reminder = await db.get(Reminder, item.source_id)
        if reminder:
            payload.update({
                "title": reminder.text,
                "context": reminder.context,
                "body": reminder.context,
                "due_at": reminder.due_at.isoformat() if reminder.due_at else payload.get("due_at"),
                "recurrence": reminder.recurrence,
                "recurrence_days": reminder.recurrence_days,
                "recurrence_ends_at": (
                    reminder.recurrence_ends_at.isoformat()
                    if reminder.recurrence_ends_at
                    else None
                ),
                "last_triggered_at": (
                    reminder.last_triggered_at.isoformat()
                    if reminder.last_triggered_at
                    else None
                ),
            })
    return {"item": payload}


async def _idea_payloads(db: AsyncSession, group_id: int, limit: int | None = None, room_id=None) -> list[dict]:
    stmt = (
        select(Idea, User.id, User.username, User.nickname, User.role, User.avatar_url)
        .outerjoin(User, Idea.created_by_user_id == User.id)
        .where(Idea.group_id == group_id)
        .order_by(desc(Idea.created_at))
    )
    if room_id is not None:
        stmt = stmt.where(Idea.room_id == room_id)
    if limit:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    rows = result.fetchall()
    ids = [idea.id for idea, *_ in rows]
    reactions = await _reaction_summary(db, "idea", ids)
    comments = await _comment_counts(db, "idea", ids)
    hub_items = await _hub_item_metadata_for_sources(db, "idea", ids)
    return [
        _apply_hub_metadata({
            "id": idea.id,
            "title": idea.title,
            "description": idea.description,
            "category": idea.category,
            "status": idea.status.value if hasattr(idea.status, "value") else idea.status,
            "creator": _user_payload_from_row(user_id, username, nickname, role, avatar_url),
            "created_at": idea.created_at.isoformat() if idea.created_at else None,
            "updated_at": idea.updated_at.isoformat() if idea.updated_at else None,
            "reactions": reactions.get(idea.id, []),
            "comment_count": comments.get(idea.id, 0),
        }, hub_items.get(idea.id))
        for idea, user_id, username, nickname, role, avatar_url in rows
        if hub_items.get(idea.id, {}).get("status") != HubItemStatus.archived.value
    ]


class GroupNoticeUpdateRequest(BaseModel):
    notice: str | None = None


async def _room_settings_for_update(db: AsyncSession, room_id: uuid.UUID) -> RoomSettings:
    settings = await db.get(RoomSettings, room_id)
    if settings is None:
        settings = RoomSettings(room_id=room_id)
        db.add(settings)
        await db.flush()
    return settings


@router.get("/group-notice")
async def get_group_notice(
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    settings = await db.get(RoomSettings, room_id)
    return {"notice": settings.notice if settings and settings.notice else ""}


@router.patch("/group-notice")
async def update_group_notice(
    request: GroupNoticeUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )

    from app.domains.rooms.repository import RoomRepository

    if not (_is_admin_user(user) or await RoomRepository(db).is_admin(room_id, user.id)):
        raise HTTPException(status_code=403, detail="Admin required")
    settings = await _room_settings_for_update(db, room_id)
    settings.notice = (request.notice or "").strip() or None
    settings.updated_at = datetime.utcnow()
    await db.commit()
    return {"notice": settings.notice or ""}


async def _dashboard_activity_for_room(
    db: AsyncSession,
    group_id: int,
    room_id,
    *,
    visible_source_ids: dict[str, set[int]],
    visible_short_ids: set[str],
) -> list[dict]:
    activity_result = await db.execute(
        select(ActivityLog, User.id, User.username, User.nickname, User.role, User.avatar_url)
        .outerjoin(User, ActivityLog.actor_user_id == User.id)
        .where(ActivityLog.group_id == group_id)
        .order_by(desc(ActivityLog.created_at))
        .limit(100)
    )

    visible_keys = {
        (target_type, target_id)
        for target_type, target_ids in visible_source_ids.items()
        for target_id in target_ids
    }
    room_message_ids: set[int] = set()
    room_event_post_ids: set[int] = set()
    if room_id is not None:
        message_ids = [
            message_id
            for message_id, in (
                await db.execute(
                    select(Message.id)
                    .where(Message.room_id == room_id)
                    .order_by(desc(Message.created_at))
                    .limit(200)
                )
            ).fetchall()
        ]
        room_message_ids = set(message_ids)
        event_ids = visible_source_ids.get("event", set())
        if event_ids:
            event_post_ids = [
                post_id
                for post_id, in (
                    await db.execute(
                        select(EventPost.id)
                        .where(EventPost.group_id == group_id, EventPost.event_id.in_(event_ids))
                    )
                ).fetchall()
            ]
            room_event_post_ids = set(event_post_ids)

    activity = []
    for item, user_id, username, nickname, role, avatar_url in activity_result.fetchall():
        target_key = (item.target_type, item.target_id)
        is_visible = target_key in visible_keys
        if item.target_type == "message" and item.target_id in room_message_ids:
            is_visible = True
        if item.target_type == "event_post" and item.target_id in room_event_post_ids:
            is_visible = True
        if item.target_type == "hub_item" and item.target_id is None:
            summary = item.summary or ""
            is_visible = any(short_id in summary for short_id in visible_short_ids)
        if not is_visible:
            continue
        activity.append({
            "id": item.id,
            "action": item.action.value if hasattr(item.action, "value") else item.action,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "summary": item.summary,
            "actor": _user_payload_from_row(user_id, username, nickname, role, avatar_url),
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })
        if len(activity) >= 40:
            break
    return activity


@router.get("/dashboard")
async def get_dashboard(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )

    ideas = await _idea_payloads(db, group.id, limit=5, room_id=room_id)
    events_data = await get_events(
        x_room_slug=x_room_slug,
        authorization=authorization,
        session_cookie=session_cookie,
        db=db,
    )
    polls = await _poll_payloads(db, group.id, room_id=room_id)
    live_polls = [poll for poll in polls if poll.get("status") == PollStatus.live.value]
    reminders = await _reminder_payloads(db, group.id, room_id=room_id)
    pinned_items = await _hub_item_payloads(db, group.id, pinned=True, limit=6, room_id=room_id)

    # Pinned chat messages surface in the noticeboard alongside pinned hub items.
    pinned_message_rows = (await db.execute(
        select(Message, User.nickname, User.avatar_url, User.avatar_emoji)
        .outerjoin(User, Message.user_session_id == User.session_id)
        .where(
            Message.room_id == room_id,
            Message.is_pinned.is_(True),
            Message.is_deleted.is_(False),
        )
        .order_by(desc(Message.pinned_at), desc(Message.id))
        .limit(20)
    )).fetchall()
    pinned_messages = [
        {
            "type": "message",
            "id": f"message-{msg.id}",
            "message_id": msg.id,
            "title": nickname or "Member",
            "body": (msg.content or "")[:200],
            "sender_nickname": nickname or "Member",
            "sender_avatar_url": avatar_url,
            "sender_avatar_emoji": avatar_emoji,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "pinned_at": msg.pinned_at.isoformat() if msg.pinned_at else None,
        }
        for msg, nickname, avatar_url, avatar_emoji in pinned_message_rows
    ]
    pinned_items = pinned_messages + pinned_items

    note_ids = {
        note_id
        for note_id, in (
            await db.execute(
                select(Note.id).where(Note.room_id == room_id, Note.archived_at.is_(None))
            )
        ).fetchall()
    }

    visible_source_ids = {
        "idea": {item["id"] for item in ideas},
        "event": {item["id"] for item in events_data["events"]},
        "poll": {item["id"] for item in polls},
        "reminder": {item["id"] for item in reminders},
        "note": note_ids,
    }
    visible_short_ids = {
        item.get("short_id")
        for collection in (ideas, events_data["events"], polls, reminders, pinned_items)
        for item in collection
        if item.get("short_id")
    }
    activity = await _dashboard_activity_for_room(
        db,
        group.id,
        room_id,
        visible_source_ids=visible_source_ids,
        visible_short_ids=visible_short_ids,
    )
    room_settings = await db.get(RoomSettings, room_id)

    counts = {
        "ideas": (
            await db.execute(
                select(func.count(Idea.id)).where(Idea.group_id == group.id, Idea.room_id == room_id)
            )
        ).scalar() or 0,
        "polls": (
            await db.execute(
                select(func.count(Poll.id)).where(Poll.group_id == group.id, Poll.room_id == room_id)
            )
        ).scalar() or 0,
        "events": (
            await db.execute(
                select(func.count(Event.id)).where(Event.group_id == group.id, Event.room_id == room_id)
            )
        ).scalar() or 0,
        "open_reminders": (
            await db.execute(
                select(func.count(Reminder.id)).where(
                    Reminder.group_id == group.id,
                    Reminder.room_id == room_id,
                    Reminder.is_completed.is_(False),
                )
            )
        ).scalar() or 0,
        "notes": (
            await db.execute(
                select(func.count(Note.id)).where(Note.room_id == room_id, Note.archived_at.is_(None))
            )
        ).scalar() or 0,
        "activity": len(activity),
    }
    return {
        "activity": activity,
        "latest_ideas": ideas,
        "pinned_items": pinned_items,
        "group_notice": room_settings.notice if room_settings and room_settings.notice else "",
        "upcoming_events": events_data["events"][:5],
        "active_polls": live_polls[:5],
        "open_reminders": [item for item in reminders if not item["is_completed"]][:5],
        "counts": counts,
    }


@router.get("/ideas")
async def get_ideas(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    ideas = await _idea_payloads(db, group.id, room_id=room_id)
    return {"ideas": ideas, "total": len(ideas)}


@router.post("/ideas")
async def create_idea(
    request: IdeaCreateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    status = request.status.strip().lower()
    if status not in {item.value for item in IdeaStatus}:
        raise HTTPException(status_code=400, detail="Invalid idea status")
    idea = Idea(
        group_id=group.id,
        room_id=room_id,
        title=_clean_text(request.title, field="Title", max_length=160),
        description=_optional_text(request.description, max_length=2000),
        category=_clean_text(request.category or "general", field="Category", max_length=60).lower(),
        status=IdeaStatus(status),
        created_by_user_id=user.id,
    )
    db.add(idea)
    await db.flush()
    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="idea",
        source_id=idea.id,
        title=idea.title,
        body=idea.description,
        tags=[idea.category],
        status=_hub_item_status_from_legacy("idea", idea.status.value if hasattr(idea.status, "value") else idea.status),
        created_by_user_id=user.id,
        room_id=room_id,
    )
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="idea", target_id=idea.id, summary=f"{user.nickname} created idea: {idea.title}")
    await db.commit()
    return {"idea": (await _idea_payloads(db, group.id, limit=None, room_id=room_id))[0]}


@router.patch("/ideas/{idea_id}")
async def update_idea(
    idea_id: int,
    request: IdeaUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    idea = await db.get(Idea, idea_id)
    if not idea or idea.group_id != group.id or idea.room_id != room_id:
        raise HTTPException(status_code=404, detail="Idea not found")
    # Status-only updates are allowed for any member (used by the Ideas board to flip
    # maybe → planned → done). Other edits require creator or admin.
    other_fields_set = any(
        _field_was_set(request, name) for name in ("title", "description", "category", "tags")
    )
    if other_fields_set and not _can_manage_creator_owned_item(user, idea.created_by_user_id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can edit this item")

    hub_item = await _load_hub_item_for_source(db, "idea", idea.id)
    current_tags = list(hub_item.tags or []) if hub_item else []

    before = {
        "title": idea.title,
        "description": idea.description,
        "category": idea.category,
        "status": idea.status,
        "tags": _clean_tags(current_tags),
    }
    if request.title is not None:
        idea.title = _clean_text(request.title, field="Title", max_length=160)
    if request.description is not None:
        idea.description = _optional_text(request.description, max_length=2000)
    if request.category is not None:
        idea.category = _clean_text(request.category, field="Category", max_length=60).lower()
    if request.status is not None:
        status = request.status.strip().lower()
        if status not in {item.value for item in IdeaStatus}:
            raise HTTPException(status_code=400, detail="Invalid idea status")
        idea.status = IdeaStatus(status)

    next_tags = current_tags
    if request.tags is not None:
        next_tags = list(request.tags)
    elif request.category is not None:
        next_tags = [idea.category]

    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="idea",
        source_id=idea.id,
        title=idea.title,
        body=idea.description,
        tags=next_tags,
        status=_hub_item_status_from_legacy("idea", idea.status.value if hasattr(idea.status, "value") else idea.status),
        created_by_user_id=idea.created_by_user_id,
        room_id=room_id,
    )
    after = {
        "title": idea.title,
        "description": idea.description,
        "category": idea.category,
        "status": idea.status,
        "tags": _clean_tags(next_tags),
    }
    await _record_history(db, "idea", idea.id, user.id, before, after)
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="idea", target_id=idea.id, summary=f"{user.nickname} updated idea: {idea.title}")
    await db.commit()
    return {"status": "updated"}


@router.delete("/ideas/{idea_id}")
async def delete_idea(
    idea_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    idea = await db.get(Idea, idea_id)
    if not idea or idea.group_id != group.id or idea.room_id != room_id:
        raise HTTPException(status_code=404, detail="Idea not found")
    if not _can_manage_creator_owned_item(user, idea.created_by_user_id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can delete this item")
    title = idea.title
    hub_item = (await db.execute(select(HubItem).where(HubItem.source_type == "idea", HubItem.source_id == idea_id, HubItem.room_id == room_id))).scalar_one_or_none()
    if hub_item:
        hub_item.status = HubItemStatus.archived.value
        hub_item.pinned_to_home = False
        hub_item.updated_at = datetime.utcnow()
    else:
        await _hub_item_for_source(
            db,
            group_id=group.id,
            item_type="idea",
            source_id=idea.id,
            title=idea.title,
            body=idea.description,
            tags=[idea.category],
            status=HubItemStatus.archived.value,
            created_by_user_id=idea.created_by_user_id,
            room_id=room_id,
        )
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.deleted, target_type="idea", target_id=idea_id, summary=f"{user.nickname} archived idea: {title}")
    await db.commit()
    return {"status": "archived"}


BOT_USER_SESSION_ID = "00000000-0000-0000-0000-000000000b07"
BOT_NICKNAME = "Hub Bot"


def _derive_poll_status(poll: Poll) -> str:
    explicit = poll.status
    if explicit == PollStatus.cancelled.value:
        return explicit
    now = datetime.utcnow()
    closes_at = poll.deadline_at
    opens_at = poll.voting_opens_at
    # Strip tzinfo so naive and aware datetimes from the DB compare cleanly.
    if closes_at and hasattr(closes_at, 'tzinfo') and closes_at.tzinfo is not None:
        closes_at = closes_at.replace(tzinfo=None)
    if opens_at and hasattr(opens_at, 'tzinfo') and opens_at.tzinfo is not None:
        opens_at = opens_at.replace(tzinfo=None)
    if closes_at and closes_at <= now:
        return PollStatus.closed.value
    if opens_at and opens_at > now:
        return PollStatus.scheduled.value
    return PollStatus.live.value


def _format_dt_short(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.strftime("%a %d %b, %H:%M")


def _format_chat_event_announcement(
    poll: Poll,
    target_user: User | None,
    options: list[str],
) -> str:
    if poll.event_type == PollEventType.nickname_vote.value and target_user:
        line = f"Rename {target_user.nickname} to \"{poll.proposed_nickname}\""
    elif poll.event_type == PollEventType.role_vote.value and target_user:
        line = f"Give {target_user.nickname} the role \"{poll.proposed_role}\""
    else:
        line = poll.question
    # Timing is shown inside the agenda card below this message, localised to
    # the viewer's timezone — do not embed UTC times in the prose.
    body = f"📜 Council motion scheduled\n{line}"
    if poll.event_type == PollEventType.general_vote.value and options:
        body += "\nOptions: " + ", ".join(options)
    return body[:1000]


def _event_type_label(event_type: str | None) -> str | None:
    if not event_type:
        return None
    return {
        PollEventType.nickname_vote.value: "Nickname motion",
        PollEventType.role_vote.value: "Role motion",
        PollEventType.general_vote.value: "Council motion",
    }.get(event_type)


def _agenda_motion_marker(poll_id: int) -> str:
    return f"[[agenda-poll:{poll_id}]]"


def _clear_poll_winner(options: list[dict]) -> dict | None:
    if not options:
        return None
    winner_option = max(options, key=lambda o: o["vote_count"])
    winner_votes = int(winner_option.get("vote_count") or 0)
    if winner_votes <= 0:
        return None
    tied = [
        option for option in options
        if int(option.get("vote_count") or 0) == winner_votes
    ]
    if len(tied) > 1:
        return None
    return winner_option


async def _apply_closed_agenda_result_if_needed(
    db: AsyncSession,
    poll: Poll,
    options: list[dict],
    status: str,
) -> bool:
    if (
        status != PollStatus.closed.value
        or poll.source != POLL_SOURCE_CHAT_AGENDA
        or poll.event_type not in (PollEventType.nickname_vote.value, PollEventType.role_vote.value)
        or not poll.target_user_id
    ):
        return False

    from app.domains.members.profile import ProfileError, validate_display_role, validate_nickname

    changed = False
    if poll.status != PollStatus.closed.value:
        poll.status = PollStatus.closed.value
        changed = True

    winner = _clear_poll_winner(options)
    winner_label = (winner.get("label") if winner else "").strip().lower()
    if winner_label != "yes":
        if changed:
            await db.commit()
        return changed

    target = await db.get(User, poll.target_user_id)
    if not target:
        if changed:
            await db.commit()
        return changed

    try:
        if poll.event_type == PollEventType.nickname_vote.value:
            proposed = validate_nickname(poll.proposed_nickname or "")
            if target.nickname != proposed:
                target.nickname = proposed
                changed = True
        else:
            proposed = validate_display_role(poll.proposed_role or "")
            if target.display_role != proposed:
                target.display_role = proposed
                changed = True
    except ProfileError:
        if changed:
            await db.commit()
        return changed

    if changed:
        target.updated_at = datetime.utcnow()
        await db.commit()
    return changed


async def _build_poll_card(
    db: AsyncSession,
    poll: Poll,
    current_user_id: uuid.UUID | None,
) -> dict | None:
    """Build a compact card payload for a single poll, suitable for chat rendering."""
    if poll is None:
        return None
    option_rows = await db.execute(
        select(PollOption, func.count(PollVote.id))
        .outerjoin(PollVote, PollOption.id == PollVote.option_id)
        .where(PollOption.poll_id == poll.id)
        .group_by(PollOption.id)
        .order_by(PollOption.position.asc(), PollOption.id.asc())
    )
    options: list[dict] = []
    total_votes = 0
    for option, count in option_rows.fetchall():
        count = int(count or 0)
        total_votes += count
        options.append({
            "id": option.id,
            "label": option.label,
            "position": option.position,
            "vote_count": count,
        })

    status = _derive_poll_status(poll)
    await _apply_closed_agenda_result_if_needed(db, poll, options, status)

    current_user_vote: list[int] = []
    if current_user_id is not None:
        vote_rows = await db.execute(
            select(PollVote.option_id).where(
                PollVote.poll_id == poll.id,
                PollVote.user_id == current_user_id,
            )
        )
        current_user_vote = [row[0] for row in vote_rows.fetchall()]

    target_user_payload = None
    if poll.target_user_id:
        target_row = await db.execute(
            select(User.id, User.username, User.nickname, User.role, User.avatar_url)
            .where(User.id == poll.target_user_id)
        )
        first = target_row.first()
        if first:
            target_user_payload = _user_payload_from_row(*first)

    creator_payload = None
    if poll.created_by_user_id:
        creator_row = await db.execute(
            select(User.id, User.username, User.nickname, User.role, User.avatar_url)
            .where(User.id == poll.created_by_user_id)
        )
        first = creator_row.first()
        if first:
            creator_payload = _user_payload_from_row(*first)

    hub_items = await _hub_item_metadata_for_sources(db, "poll", [poll.id])
    hub_meta = hub_items.get(poll.id) or {}
    title = (hub_meta.get("title") if isinstance(hub_meta, dict) else None) or poll.question

    winner = None
    if status in (PollStatus.closed.value, PollStatus.cancelled.value) and options:
        winner_option = _clear_poll_winner(options)
        if winner_option:
            winner = {
                "id": winner_option["id"],
                "label": winner_option["label"],
                "vote_count": winner_option["vote_count"],
            }

    vote_mode = poll.vote_mode.value if hasattr(poll.vote_mode, "value") else (poll.vote_mode or "single")

    return {
        "id": poll.id,
        "title": title,
        "question": poll.question,
        "event_type": poll.event_type,
        "event_type_label": _event_type_label(poll.event_type),
        "status": status,
        "is_closed": status in (PollStatus.closed.value, PollStatus.cancelled.value),
        "is_live": status == PollStatus.live.value,
        "is_scheduled": status == PollStatus.scheduled.value,
        "vote_mode": vote_mode,
        "voting_opens_at": _iso_utc(poll.voting_opens_at),
        "voting_closes_at": _iso_utc(poll.deadline_at),
        "deadline_at": _iso_utc(poll.deadline_at),
        "options": options,
        "total_votes": total_votes,
        "current_user_vote": current_user_vote,
        "has_voted": bool(current_user_vote),
        "source": poll.source,
        "target_user": target_user_payload,
        "target_user_id": str(poll.target_user_id) if poll.target_user_id else None,
        "proposed_nickname": poll.proposed_nickname,
        "proposed_role": poll.proposed_role,
        "winner": winner,
        "creator": creator_payload,
        "open_message_id": poll.open_message_id,
        "result_message_id": poll.result_message_id,
    }


async def _current_user_optional(
    authorization: str | None,
    db: AsyncSession,
    session_cookie: str | None = None,
) -> User | None:
    if not authorization and not session_cookie:
        return None
    try:
        return await _current_user_or_401(authorization, db, session_cookie)
    except HTTPException:
        return None


async def _default_room_id(db: AsyncSession):
    """Return the UUID of the default room, or None if the rooms table doesn't exist yet."""
    try:
        from app.models.room import DEFAULT_ROOM_ID
        return DEFAULT_ROOM_ID
    except Exception:
        return None


async def _request_room_id(
    db: AsyncSession,
    *,
    authorization: str | None = None,
    session_cookie: str | None = None,
    x_room_slug: str | None = None,
):
    """
    Resolve the trusted room for a request.

    Authenticated requests use membership-checked room resolution. Unauthenticated
    legacy reads fall back to the default room so the single-room app can still
    load before login state has settled.
    """
    if _auth_token(authorization, session_cookie):
        from app.domains.rooms.service import RoomService

        user = await _current_user_or_401(authorization, db, session_cookie)
        if getattr(user, "user_type", None) == "guest" and x_room_slug not in (None, "demo"):
            raise HTTPException(status_code=403, detail="Guest sessions are restricted to the demo room")
        room, error = await RoomService(db).resolve_room(slug=x_room_slug, user_id=user.id)
        if error:
            if "not found" in error or "not a member" in error:
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)
        return room.id
    return await _default_room_id(db)


async def _post_bot_chat_message(
    db: AsyncSession,
    *,
    content: str,
    manager: ConnectionManager | None,
    room_id=None,
) -> Message:
    bot_uuid = uuid.UUID(BOT_USER_SESSION_ID)
    if room_id is None:
        room_id = await _default_room_id(db)
    message = Message(
        user_session_id=bot_uuid,
        user_id=bot_uuid,
        content=content,
        created_at=datetime.utcnow(),
        room_id=room_id,
    )
    db.add(message)
    await db.flush()
    return message


async def _broadcast_bot_message(message: Message, manager: ConnectionManager | None, room_id=None) -> None:
    if manager is None:
        return
    from app.domains.chat.events import OutgoingChatMessage
    payload = OutgoingChatMessage(
        session_id=BOT_USER_SESSION_ID,
        nickname=BOT_NICKNAME,
        content=message.content,
        timestamp=message.created_at,
        message_id=message.id,
        is_bot=True,
    ).dict()
    if room_id is not None and hasattr(manager, "broadcast_to_room"):
        await manager.broadcast_to_room(room_id, payload)
    else:
        await manager.broadcast(payload)


async def _poll_payloads(db: AsyncSession, group_id: int, room_id=None) -> list[dict]:
    stmt = (
        select(Poll, User.id, User.username, User.nickname, User.role, User.avatar_url)
        .outerjoin(User, Poll.created_by_user_id == User.id)
        .where(Poll.group_id == group_id)
        .order_by(desc(Poll.created_at))
    )
    if room_id is not None:
        stmt = stmt.where(Poll.room_id == room_id)
    poll_rows = await db.execute(stmt)
    rows = poll_rows.fetchall()
    poll_ids = [poll.id for poll, *_ in rows]
    options: dict[int, list[dict]] = {poll_id: [] for poll_id in poll_ids}
    votes: dict[int, list[dict]] = {poll_id: [] for poll_id in poll_ids}
    if poll_ids:
        options_result = await db.execute(
            select(PollOption, func.count(PollVote.id))
            .outerjoin(PollVote, PollOption.id == PollVote.option_id)
            .where(PollOption.poll_id.in_(poll_ids))
            .group_by(PollOption.id)
            .order_by(PollOption.position.asc(), PollOption.id.asc())
        )
        for option, vote_count in options_result.fetchall():
            options.setdefault(option.poll_id, []).append({
                "id": option.id,
                "label": option.label,
                "position": option.position,
                "vote_count": vote_count or 0,
            })
        vote_result = await db.execute(
            select(PollVote.poll_id, PollVote.user_id, PollVote.option_id)
            .where(PollVote.poll_id.in_(poll_ids))
        )
        for poll_id, user_id, option_id in vote_result.fetchall():
            votes.setdefault(poll_id, []).append({"user_id": str(user_id), "option_id": option_id})
    reactions = await _reaction_summary(db, "poll", poll_ids)
    comments = await _comment_counts(db, "poll", poll_ids)
    hub_items = await _hub_item_metadata_for_sources(db, "poll", poll_ids)
    target_user_ids = [poll.target_user_id for poll, *_ in rows if poll.target_user_id]
    targets: dict[str, dict] = {}
    if target_user_ids:
        target_rows = await db.execute(
            select(User.id, User.username, User.nickname, User.role, User.avatar_url)
            .where(User.id.in_(target_user_ids))
        )
        for tid, uname, nick, trole, avatar in target_rows.fetchall():
            payload = _user_payload_from_row(tid, uname, nick, trole, avatar)
            if payload:
                targets[str(tid)] = payload
    payloads = []
    for poll, user_id, username, nickname, role, avatar_url in rows:
        if hub_items.get(poll.id, {}).get("status") == HubItemStatus.archived.value:
            continue
        derived_status = _derive_poll_status(poll)
        payload = {
            "id": poll.id,
            "question": poll.question,
            "vote_mode": poll.vote_mode.value if hasattr(poll.vote_mode, "value") else poll.vote_mode,
            "deadline_at": _iso_utc(poll.deadline_at),
            "voting_opens_at": _iso_utc(poll.voting_opens_at),
            "voting_closes_at": _iso_utc(poll.deadline_at),
            "is_closed": derived_status in (PollStatus.closed.value, PollStatus.cancelled.value),
            "status": derived_status,
            "event_type": poll.event_type,
            "source": poll.source,
            "proposed_nickname": poll.proposed_nickname,
            "proposed_role": poll.proposed_role,
            "target_user_id": str(poll.target_user_id) if poll.target_user_id else None,
            "target_user": targets.get(str(poll.target_user_id)) if poll.target_user_id else None,
            "open_message_id": poll.open_message_id,
            "result_message_id": poll.result_message_id,
            "linked_idea_id": poll.linked_idea_id,
            "linked_event_id": poll.linked_event_id,
            "creator": _user_payload_from_row(user_id, username, nickname, role, avatar_url),
            "created_at": _iso_utc(poll.created_at),
            "updated_at": _iso_utc(poll.updated_at),
            "options": options.get(poll.id, []),
            "votes": votes.get(poll.id, []),
            "reactions": reactions.get(poll.id, []),
            "comment_count": comments.get(poll.id, 0),
        }
        payloads.append(_apply_hub_metadata(payload, hub_items.get(poll.id)))
    return payloads


@router.get("/polls")
async def get_polls(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    polls = await _poll_payloads(db, group.id, room_id=room_id)
    return {"polls": polls, "total": len(polls)}


@router.post("/polls")
async def create_poll(
    request: PollCreateRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    mode = request.vote_mode.strip().lower()
    if mode not in {item.value for item in PollVoteMode}:
        raise HTTPException(status_code=400, detail="Invalid poll vote mode")
    option_labels = [_clean_text(option, field="Option", max_length=160) for option in request.options]
    option_labels = list(dict.fromkeys(option_labels))
    if len(option_labels) < 2:
        raise HTTPException(status_code=400, detail="At least two options are required")
    if not request.deadline_at:
        raise HTTPException(status_code=400, detail="Poll vote-by time is required")
    poll = Poll(
        group_id=group.id,
        room_id=room_id,
        question=_clean_text(request.question, field="Question", max_length=220),
        vote_mode=PollVoteMode(mode),
        deadline_at=_to_utc_naive(request.deadline_at) if request.deadline_at else None,
        linked_idea_id=request.linked_idea_id,
        linked_event_id=request.linked_event_id,
        created_by_user_id=user.id,
    )
    db.add(poll)
    await db.flush()
    for index, label in enumerate(option_labels):
        db.add(PollOption(poll_id=poll.id, label=label, position=index))
    hub_item = await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="poll",
        source_id=poll.id,
        title=poll.question,
        due_at=poll.deadline_at,
        created_by_user_id=user.id,
        room_id=room_id,
    )
    await db.flush()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="poll", target_id=poll.id, summary=f"{user.nickname} created poll: {poll.question}")
    await db.commit()
    background_tasks.add_task(
        _bg_broadcast_notification,
        user.id, user.nickname, "new_poll",
        f"{user.nickname} created a new poll: {poll.question[:80]}",
        "poll", poll.id, manager,
        send_push=False,
    )
    background_tasks.add_task(
        _bg_poll_created_push_notification,
        user.id, user.nickname, group.id, poll.id, poll.question,
        str(hub_item.id) if getattr(hub_item, "id", None) else None,
    )
    return {"status": "created", "id": poll.id}


@router.patch("/polls/{poll_id}")
async def update_poll(
    poll_id: int,
    request: PollUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    poll = await db.get(Poll, poll_id)
    if not poll or poll.group_id != group.id or poll.room_id != room_id:
        raise HTTPException(status_code=404, detail="Poll not found")
    if not _can_manage_creator_owned_item(user, poll.created_by_user_id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can edit this item")

    hub_item = await _load_hub_item_for_source(db, "poll", poll.id)
    current_title = (hub_item.title if hub_item else None) or poll.question
    current_body = hub_item.body if hub_item else None
    current_tags = list(hub_item.tags or []) if hub_item else []

    before = {
        "question": poll.question,
        "deadline_at": poll.deadline_at,
        "voting_opens_at": poll.voting_opens_at,
        "title": current_title,
        "description": current_body,
        "tags": current_tags,
    }

    if request.question is not None:
        poll.question = _clean_text(request.question, field="Question", max_length=220)
    if _field_was_set(request, "deadline_at"):
        poll.deadline_at = _to_utc_naive(request.deadline_at) if request.deadline_at else None
    if _field_was_set(request, "voting_opens_at"):
        poll.voting_opens_at = _to_utc_naive(request.voting_opens_at) if request.voting_opens_at else None
    if poll.deadline_at and poll.voting_opens_at and poll.deadline_at <= poll.voting_opens_at:
        raise HTTPException(status_code=400, detail="Voting close must be after voting open")
    if _field_was_set(request, "linked_idea_id"):
        poll.linked_idea_id = request.linked_idea_id
    if _field_was_set(request, "linked_event_id"):
        poll.linked_event_id = request.linked_event_id

    next_title = current_title
    if request.title is not None:
        next_title = _clean_text(request.title, field="Title", max_length=120)
    elif request.question is not None and poll.source != POLL_SOURCE_CHAT_AGENDA:
        # Non-agenda polls treat the question as the title.
        next_title = poll.question
    next_body = current_body
    if _field_was_set(request, "description"):
        next_body = _optional_text(request.description, max_length=2000)
    next_tags = current_tags
    if request.tags is not None:
        next_tags = list(request.tags)

    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="poll",
        source_id=poll.id,
        title=next_title,
        body=next_body,
        tags=next_tags,
        due_at=poll.deadline_at,
        created_by_user_id=poll.created_by_user_id,
        room_id=room_id,
    )

    after = {
        "question": poll.question,
        "deadline_at": poll.deadline_at,
        "voting_opens_at": poll.voting_opens_at,
        "title": next_title,
        "description": next_body,
        "tags": _clean_tags(next_tags),
    }
    before["tags"] = _clean_tags(before["tags"])
    await _record_history(db, "poll", poll.id, user.id, before, after)
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="poll", target_id=poll.id, summary=f"{user.nickname} updated poll: {next_title}")
    await db.commit()
    return {"status": "updated"}


@router.get("/polls/live-agenda")
async def list_live_agenda_motions(
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Return chat-agenda polls that are currently live, newest first, for pinning."""
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    user = await _current_user_optional(authorization, db, session_cookie)
    rows = await db.execute(
        select(Poll)
        .where(
            Poll.group_id == group.id,
            Poll.room_id == room_id,
            Poll.source == POLL_SOURCE_CHAT_AGENDA,
        )
        .order_by(desc(Poll.created_at))
    )
    motions: list[dict] = []
    user_id = user.id if user else None
    for poll in rows.scalars().all():
        if _derive_poll_status(poll) != PollStatus.live.value:
            continue
        card = await _build_poll_card(db, poll, user_id)
        if card:
            motions.append(card)
    return {"motions": motions, "total": len(motions)}


@router.get("/polls/{poll_id}/card")
async def get_poll_card(
    poll_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Compact card payload for chat rendering of a single poll."""
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    poll = await db.get(Poll, poll_id)
    if not poll or poll.group_id != group.id or poll.room_id != room_id:
        raise HTTPException(status_code=404, detail="Poll not found")
    user = await _current_user_optional(authorization, db, session_cookie)
    card = await _build_poll_card(db, poll, user.id if user else None)
    return {"card": card}


@router.post("/polls/{poll_id}/vote")
async def vote_poll(
    poll_id: int,
    request: PollVoteRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    poll = await db.get(Poll, poll_id)
    if not poll or poll.group_id != group.id or poll.room_id != room_id:
        raise HTTPException(status_code=404, detail="Poll not found")
    derived_status = _derive_poll_status(poll)
    if derived_status == PollStatus.scheduled.value:
        raise HTTPException(status_code=400, detail="Voting has not opened yet")
    if derived_status in (PollStatus.closed.value, PollStatus.cancelled.value):
        raise HTTPException(status_code=400, detail="Poll is closed")
    option_ids = list(dict.fromkeys(request.option_ids))
    if not option_ids:
        raise HTTPException(status_code=400, detail="At least one option is required")
    if (poll.vote_mode.value if hasattr(poll.vote_mode, "value") else poll.vote_mode) == "single" and len(option_ids) > 1:
        raise HTTPException(status_code=400, detail="Single-choice polls accept one option")
    valid_options = await db.execute(select(PollOption.id).where(PollOption.poll_id == poll.id, PollOption.id.in_(option_ids)))
    valid_ids = {option_id for option_id, in valid_options.fetchall()}
    if valid_ids != set(option_ids):
        raise HTTPException(status_code=400, detail="Invalid poll option")
    await db.execute(delete(PollVote).where(PollVote.poll_id == poll.id, PollVote.user_id == user.id))
    for option_id in option_ids:
        db.add(PollVote(poll_id=poll.id, option_id=option_id, user_id=user.id))
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.voted, target_type="poll", target_id=poll.id, summary=f"{user.nickname} voted in poll: {poll.question}")
    await db.commit()
    card = await _build_poll_card(db, poll, user.id)
    return {"status": "voted", "card": card}


@router.delete("/polls/{poll_id}")
async def delete_poll(
    poll_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    poll = await db.get(Poll, poll_id)
    if not poll or poll.group_id != group.id or poll.room_id != room_id:
        raise HTTPException(status_code=404, detail="Poll not found")
    if not _can_manage_creator_owned_item(user, poll.created_by_user_id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can delete this item")
    question = poll.question
    hub_item = (await db.execute(select(HubItem).where(HubItem.source_type == "poll", HubItem.source_id == poll_id, HubItem.room_id == room_id))).scalar_one_or_none()
    if hub_item:
        hub_item.status = HubItemStatus.archived.value
        hub_item.pinned_to_home = False
        hub_item.updated_at = datetime.utcnow()
    else:
        await _hub_item_for_source(
            db,
            group_id=group.id,
            item_type="poll",
            source_id=poll.id,
            title=poll.question,
            due_at=poll.deadline_at,
            status=HubItemStatus.archived.value,
            created_by_user_id=poll.created_by_user_id,
            room_id=room_id,
        )
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.deleted, target_type="poll", target_id=poll_id, summary=f"{user.nickname} archived poll: {question}")
    await db.commit()
    return {"status": "archived"}


def _validate_chat_event(
    request: ChatEventCreateRequest,
    actor: User,
) -> tuple[str, datetime, datetime]:
    event_type = (request.event_type or "").strip().lower()
    if event_type not in {item.value for item in PollEventType}:
        raise HTTPException(status_code=400, detail="Invalid event_type")
    if not request.title or not request.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")
    if not request.voting_opens_at or not request.voting_closes_at:
        raise HTTPException(status_code=400, detail="Voting opens and closes times are required")
    opens_at = _to_utc_naive(request.voting_opens_at)
    closes_at = _to_utc_naive(request.voting_closes_at)
    if closes_at <= opens_at:
        raise HTTPException(status_code=400, detail="voting_closes_at must be after voting_opens_at")
    if event_type in (PollEventType.nickname_vote.value, PollEventType.role_vote.value):
        if not _is_admin_user(actor):
            raise HTTPException(status_code=403, detail="Only admins or the owner can create this motion type")
        if not request.target_user_id:
            raise HTTPException(status_code=400, detail="target_user_id is required for this event type")
    if event_type == PollEventType.nickname_vote.value:
        if not request.proposed_nickname or not request.proposed_nickname.strip():
            raise HTTPException(status_code=400, detail="proposed_nickname is required for nickname_vote")
    if event_type == PollEventType.role_vote.value:
        if not request.proposed_role or not request.proposed_role.strip():
            raise HTTPException(status_code=400, detail="proposed_role is required for role_vote")
    if event_type == PollEventType.general_vote.value:
        if not request.poll_question or not request.poll_question.strip():
            raise HTTPException(status_code=400, detail="poll_question is required for general_vote")
        cleaned = [opt.strip() for opt in (request.poll_options or []) if opt and opt.strip()]
        cleaned = list(dict.fromkeys(cleaned))
        if len(cleaned) < 2:
            raise HTTPException(status_code=400, detail="At least two options are required")
    return event_type, opens_at, closes_at


@router.post("/chat-events")
async def create_chat_event(
    request: ChatEventCreateRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """Create a scheduled chat-agenda motion (nickname / role / general vote)."""
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event_type, opens_at, closes_at = _validate_chat_event(request, user)

    target_user: User | None = None
    proposed_nickname: str | None = None
    proposed_role: str | None = None
    if event_type in (PollEventType.nickname_vote.value, PollEventType.role_vote.value):
        try:
            target_uuid = uuid.UUID(request.target_user_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid target_user_id")
        result = await db.execute(select(User).where(User.id == target_uuid))
        target_user = result.scalar_one_or_none()
        if not target_user:
            raise HTTPException(status_code=404, detail="Target user not found")

    if event_type == PollEventType.nickname_vote.value:
        proposed_nickname = request.proposed_nickname.strip()[:50]
        question = f"Should {target_user.nickname} be renamed \"{proposed_nickname}\"?"
        option_labels = ["Yes", "No"]
    elif event_type == PollEventType.role_vote.value:
        proposed_role = request.proposed_role.strip()[:64]
        question = f"Should {target_user.nickname} become \"{proposed_role}\"?"
        option_labels = ["Yes", "No"]
    else:
        question = _clean_text(request.poll_question, field="Question", max_length=220)
        option_labels = [_clean_text(opt, field="Option", max_length=160) for opt in request.poll_options]
        option_labels = list(dict.fromkeys(option_labels))

    poll = Poll(
        group_id=group.id,
        room_id=room_id,
        question=question,
        vote_mode=PollVoteMode.single,
        deadline_at=closes_at,
        voting_opens_at=opens_at,
        event_type=event_type,
        target_user_id=target_user.id if target_user else None,
        proposed_nickname=proposed_nickname,
        proposed_role=proposed_role,
        source=POLL_SOURCE_CHAT_AGENDA,
        created_by_user_id=user.id,
    )
    poll.status = _derive_poll_status(poll)
    db.add(poll)
    await db.flush()
    for index, label in enumerate(option_labels):
        db.add(PollOption(poll_id=poll.id, label=label, position=index))

    title = _clean_text(request.title, field="Title", max_length=120)
    body = _optional_text(request.description, max_length=2000)
    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="poll",
        source_id=poll.id,
        title=title,
        body=body,
        tags=["agenda", event_type],
        due_at=poll.deadline_at,
        created_by_user_id=user.id,
        room_id=room_id,
    )

    announcement = _format_chat_event_announcement(poll, target_user, option_labels)
    announcement_with_marker = f"{announcement}\n{_agenda_motion_marker(poll.id)}"
    chat_message = await _post_bot_chat_message(db, content=announcement_with_marker, manager=manager, room_id=room_id)
    poll.open_message_id = chat_message.id

    await _log_activity(
        db,
        group_id=group.id,
        actor_user_id=user.id,
        action=ActivityAction.created,
        target_type="poll",
        target_id=poll.id,
        summary=f"{user.nickname} scheduled motion: {title}",
    )
    await db.commit()
    await db.refresh(chat_message)

    await _broadcast_bot_message(chat_message, manager, room_id=room_id)
    background_tasks.add_task(
        _bg_broadcast_notification,
        user.id, user.nickname, "new_chat_event",
        f"{user.nickname} scheduled a motion: {title[:80]}",
        "poll", poll.id, manager,
    )
    return {
        "status": "created",
        "id": poll.id,
        "poll_status": poll.status,
        "open_message_id": chat_message.id,
    }


@router.get("/events")
async def get_events(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    result = await db.execute(
        select(
            Event,
            User.nickname,
            User.id,
            User.username,
            User.role,
            func.count(EventRsvp.id).filter(EventRsvp.response == "yes").label("yes_count"),
            func.count(EventRsvp.id).filter(EventRsvp.response == "maybe").label("maybe_count"),
            func.count(EventRsvp.id).filter(EventRsvp.response == "no").label("no_count"),
        )
        .outerjoin(User, Event.created_by_session_id == User.session_id)
        .outerjoin(EventRsvp, Event.id == EventRsvp.event_id)
        .where(Event.group_id == group.id, Event.room_id == room_id, Event.archived_at.is_(None))
        .group_by(Event.id, User.nickname, User.id, User.username, User.role)
        .order_by(Event.starts_at.asc())
    )

    rows = result.fetchall()
    ids = [event.id for event, *_ in rows]
    reactions = await _reaction_summary(db, "event", ids)
    comments = await _comment_counts(db, "event", ids)
    hub_items = await _hub_item_metadata_for_sources(db, "event", ids)
    invites_by_event: dict[int, list[dict]] = {event_id: [] for event_id in ids}
    rsvps_by_event: dict[int, list[dict]] = {event_id: [] for event_id in ids}
    if ids:
        invite_result = await db.execute(
            select(EventInvite.event_id, User.id, User.username, User.nickname, User.role)
            .join(User, EventInvite.user_id == User.id)
            .where(EventInvite.event_id.in_(ids))
            .order_by(User.nickname.asc())
        )
        for event_id, user_id, username, nickname, role in invite_result.fetchall():
            invites_by_event.setdefault(event_id, []).append(_user_payload_from_row(user_id, username, nickname, role))
        rsvp_result = await db.execute(
            select(EventRsvp.event_id, EventRsvp.response, User.id, User.username, User.nickname, User.role, User.avatar_url)
            .join(User, EventRsvp.user_session_id == User.session_id)
            .where(EventRsvp.event_id.in_(ids))
            .order_by(User.nickname.asc())
        )
        for event_id, response, user_id, username, nickname, role, avatar_url in rsvp_result.fetchall():
            rsvps_by_event.setdefault(event_id, []).append({
                "response": response,
                "user": _user_payload_from_row(user_id, username, nickname, role, avatar_url),
            })
    events = []
    for event, nickname, user_id, username, role, yes_count, maybe_count, no_count in rows:
        hub_metadata = hub_items.get(event.id)
        creator = _event_creator_payload(user_id, username, nickname, role, hub_metadata)
        if hub_metadata and not nickname and creator:
            nickname = creator.get("nickname")
        if hub_metadata and hub_metadata.get("status") == HubItemStatus.archived.value:
            continue
        events.append(_apply_hub_metadata({
            "id": event.id,
            "title": event.title,
            "description": event.description,
            "location": event.location,
            "cover_photo_url": event.cover_photo_url,
            "photo_tag_id": event.photo_tag_id,
            "starts_at": event.starts_at.isoformat() if event.starts_at else None,
            "linked_poll_id": event.linked_poll_id,
            "created_by": nickname,
            "creator": creator,
            "invites": invites_by_event.get(event.id, []),
            "yes_count": yes_count or 0,
            "maybe_count": maybe_count or 0,
            "no_count": no_count or 0,
            "rsvps": rsvps_by_event.get(event.id, []),
            "reactions": reactions.get(event.id, []),
            "comment_count": comments.get(event.id, 0),
        }, hub_metadata))
    return {"events": events, "total": len(events)}


@router.get("/events/{event_id}/card")
async def get_event_card(
    event_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Compact event card payload for chat rendering."""
    await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)
    rsvp_result = await db.execute(
        select(EventRsvp.response, func.count(EventRsvp.id))
        .where(EventRsvp.event_id == event_id)
        .group_by(EventRsvp.response)
    )
    rsvp_counts = {"yes": 0, "maybe": 0, "no": 0}
    for response, count in rsvp_result.fetchall():
        if response in rsvp_counts:
            rsvp_counts[response] = int(count)
    return {
        "id": event.id,
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "starts_at": event.starts_at.isoformat() if event.starts_at else None,
        "ends_at": None,
        **rsvp_counts,
    }


@router.get("/events/{event_id}/calendar.ics")
async def get_event_calendar_ics(
    event_id: int,
    request: Request,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)

    base_url = str(request.base_url).rstrip("/")
    event_url = f"{base_url}/events/{event.id}"
    content = build_event_ics(event, event_url=event_url)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="friend-hub-event-{event.id}.ics"',
        },
    )

@router.post("/events")
async def create_event(
    request: EventCreateRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )

    event = Event(
        group_id=group.id,
        room_id=room_id,
        title=_clean_text(request.title, field="Title", max_length=120),
        description=_optional_text(request.description, max_length=2000),
        location=_optional_text(request.location, max_length=160),
        cover_photo_url=_optional_url(request.cover_photo_url),
        photo_tag_id=_optional_tag_id(request.photo_tag_id),
        starts_at=_to_utc_naive(request.starts_at),
        linked_poll_id=request.linked_poll_id,
        created_by_session_id=user.session_id,
    )
    db.add(event)
    await db.flush()
    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="event",
        source_id=event.id,
        title=event.title,
        body=event.description,
        event_start_at=event.starts_at,
        created_by_user_id=user.id,
        room_id=room_id,
    )
    if event.photo_tag_id is None:
        hub_item = (await db.execute(select(HubItem).where(
            HubItem.source_type == "event",
            HubItem.source_id == event.id,
            HubItem.room_id == room_id,
        ))).scalar_one_or_none()
        event.photo_tag_id = hub_item.short_id if hub_item else f"#E-{event.id}"
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="event", target_id=event.id, summary=f"{user.nickname} created event: {event.title}")
    await db.commit()
    await db.refresh(event)
    background_tasks.add_task(
        _bg_broadcast_notification,
        user.id, user.nickname, "new_event",
        f"{user.nickname} created a new event: {event.title[:80]}",
        "event", event.id, manager
    )
    return {"event": {"id": event.id, "title": event.title, "starts_at": event.starts_at.isoformat()}}

@router.patch("/events/{event_id}")
async def update_event(
    event_id: int,
    request: EventUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)
    _require_event_editor(user, event)
    hub_item = await _load_hub_item_for_source(db, "event", event.id)
    current_tags = list(hub_item.tags or []) if hub_item else []
    before = {
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "starts_at": event.starts_at,
        "cover_photo_url": event.cover_photo_url,
        "tags": _clean_tags(current_tags),
    }
    if request.title is not None:
        event.title = _clean_text(request.title, field="Title", max_length=120)
    if _field_was_set(request, "description"):
        event.description = _optional_text(request.description, max_length=2000)
    if _field_was_set(request, "location"):
        event.location = _optional_text(request.location, max_length=160)
    if _field_was_set(request, "cover_photo_url"):
        event.cover_photo_url = _optional_url(request.cover_photo_url)
    if _field_was_set(request, "photo_tag_id"):
        event.photo_tag_id = _optional_tag_id(request.photo_tag_id)
    if request.starts_at is not None:
        event.starts_at = _to_utc_naive(request.starts_at)
    if _field_was_set(request, "linked_poll_id"):
        event.linked_poll_id = request.linked_poll_id
    next_tags = current_tags
    if request.tags is not None:
        next_tags = list(request.tags)
    after = {
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "starts_at": event.starts_at,
        "cover_photo_url": event.cover_photo_url,
        "tags": _clean_tags(next_tags),
    }
    await _record_history(db, "event", event.id, user.id, before, after)
    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="event",
        source_id=event.id,
        title=event.title,
        body=event.description,
        tags=next_tags,
        event_start_at=event.starts_at,
        created_by_user_id=user.id,
        room_id=room_id,
    )
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="event", target_id=event.id, summary=f"{user.nickname} updated event: {event.title}")
    await db.commit()
    return {"status": "updated"}


@router.put("/events/{event_id}/invites")
async def update_event_invites(
    event_id: int,
    request: EventInviteUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)
    _require_event_editor(user, event)
    clean_ids = list(dict.fromkeys([value for value in request.user_ids if value]))
    valid_users = []
    if clean_ids:
        valid_result = await db.execute(select(User.id).where(User.id.in_(clean_ids), User.is_active.is_(True)))
        valid_users = valid_result.scalars().all()
    await db.execute(delete(EventInvite).where(EventInvite.event_id == event.id))
    for user_id in valid_users:
        db.add(EventInvite(event_id=event.id, user_id=user_id, invited_by_user_id=user.id))
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="event", target_id=event.id, summary=f"{user.nickname} updated invites for event: {event.title}")
    await db.commit()
    return {"status": "updated", "invited_user_ids": [str(user_id) for user_id in valid_users]}


@router.post("/events/{event_id}/rsvp")
async def rsvp_event(
    event_id: int,
    request: RsvpRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)
    if request.response not in {"yes", "maybe", "no"}:
        raise HTTPException(status_code=400, detail="RSVP must be yes, maybe, or no")

    stmt = insert(EventRsvp).values(
        event_id=event_id,
        user_session_id=user.session_id,
        response=request.response,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["event_id", "user_session_id"],
        set_={"response": request.response, "updated_at": func.now()},
    )
    await db.execute(stmt)
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.rsvped, target_type="event", target_id=event.id, summary=f"{user.nickname} RSVP'd {request.response} to {event.title}")
    await db.commit()
    return {"status": "updated"}


async def _event_post_payloads(db: AsyncSession, group_id: int, event_id: int) -> list[dict]:
    result = await db.execute(
        select(EventPost, User.id, User.username, User.nickname, User.role)
        .outerjoin(User, EventPost.created_by_user_id == User.id)
        .where(EventPost.group_id == group_id, EventPost.event_id == event_id)
        .order_by(desc(EventPost.created_at))
    )
    rows = result.fetchall()
    ids = [post.id for post, *_ in rows]
    comment_counts = await _comment_counts(db, "event_post", ids)
    return [
        {
            "id": post.id,
            "event_id": post.event_id,
            "content": post.content,
            "creator": _user_payload_from_row(user_id, username, nickname, role),
            "comment_count": comment_counts.get(post.id, 0),
            "created_at": post.created_at.isoformat() if post.created_at else None,
            "updated_at": post.updated_at.isoformat() if post.updated_at else None,
        }
        for post, user_id, username, nickname, role in rows
    ]


@router.get("/events/{event_id}/posts")
async def get_event_posts(
    event_id: int,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)
    posts = await _event_post_payloads(db, group.id, event.id)
    return {"posts": posts, "total": len(posts)}


@router.post("/events/{event_id}/posts")
async def create_event_post(
    event_id: int,
    request: EventPostCreateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    event = await _event_by_id_or_404(db, group.id, event_id, room_id=room_id)
    post = EventPost(
        group_id=group.id,
        event_id=event.id,
        content=_clean_text(request.content, field="Post", max_length=2000),
        created_by_user_id=user.id,
    )
    db.add(post)
    await db.flush()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="event_post", target_id=post.id, summary=f"{user.nickname} posted on event: {event.title}")
    await db.commit()
    return {"status": "created", "id": post.id}


_VALID_RECURRENCES = {"daily", "weekly", "every_N_days"}

def _validated_recurrence(recurrence: str | None, recurrence_days: int | None) -> str | None:
    if not recurrence:
        return None
    if recurrence not in _VALID_RECURRENCES:
        raise HTTPException(status_code=400, detail=f"recurrence must be one of: {', '.join(_VALID_RECURRENCES)}")
    if recurrence == "every_N_days":
        if not recurrence_days or not (2 <= recurrence_days <= 365):
            raise HTTPException(status_code=400, detail="recurrence_days must be 2–365 when recurrence is 'every_N_days'")
    return recurrence


async def _reminder_payloads(db: AsyncSession, group_id: int, room_id=None) -> list[dict]:
    where_clauses = [Reminder.group_id == group_id]
    if room_id is not None:
        where_clauses.append(Reminder.room_id == room_id)
    result = await db.execute(
        select(Reminder, User.id, User.username, User.nickname, User.role, User.avatar_url)
        .outerjoin(User, Reminder.created_by_user_id == User.id)
        .where(*where_clauses)
        .order_by(Reminder.is_completed.asc(), Reminder.due_at.asc().nulls_last(), desc(Reminder.created_at))
    )
    rows = result.fetchall()
    ids = [reminder.id for reminder, *_ in rows]
    assignees: dict[int, list[dict]] = {reminder_id: [] for reminder_id in ids}
    if ids:
        assignee_result = await db.execute(
            select(ReminderAssignee.reminder_id, User.id, User.username, User.nickname, User.role)
            .join(User, ReminderAssignee.user_id == User.id)
            .where(ReminderAssignee.reminder_id.in_(ids))
            .order_by(User.nickname.asc())
        )
        for reminder_id, user_id, username, nickname, role in assignee_result.fetchall():
            assignees.setdefault(reminder_id, []).append(_user_payload_from_row(user_id, username, nickname, role))
    reactions = await _reaction_summary(db, "reminder", ids)
    comments = await _comment_counts(db, "reminder", ids)
    hub_items = await _hub_item_metadata_for_sources(db, "reminder", ids)
    return [
        _apply_hub_metadata({
            "id": reminder.id,
            "title": reminder.text,
            "text": reminder.text,
            "context": reminder.context,
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
            "linked_event_id": reminder.linked_event_id,
            "is_completed": bool(reminder.is_completed),
            "completed_at": reminder.completed_at.isoformat() if reminder.completed_at else None,
            "recurrence": reminder.recurrence,
            "recurrence_days": reminder.recurrence_days,
            "recurrence_ends_at": reminder.recurrence_ends_at.isoformat() if reminder.recurrence_ends_at else None,
            "last_triggered_at": reminder.last_triggered_at.isoformat() if reminder.last_triggered_at else None,
            "creator": _user_payload_from_row(user_id, username, nickname, role, avatar_url),
            "assignees": assignees.get(reminder.id, []),
            "created_at": reminder.created_at.isoformat() if reminder.created_at else None,
            "updated_at": reminder.updated_at.isoformat() if reminder.updated_at else None,
            "reactions": reactions.get(reminder.id, []),
            "comment_count": comments.get(reminder.id, 0),
        }, hub_items.get(reminder.id))
        for reminder, user_id, username, nickname, role, avatar_url in rows
        if hub_items.get(reminder.id, {}).get("status") != HubItemStatus.archived.value
    ]


async def _replace_reminder_assignees(db: AsyncSession, reminder_id: int, user_ids: list[str]):
    await db.execute(delete(ReminderAssignee).where(ReminderAssignee.reminder_id == reminder_id))
    clean_ids = list(dict.fromkeys([value for value in user_ids if value]))
    if not clean_ids:
        return
    valid_users = await db.execute(select(User.id).where(User.id.in_(clean_ids)))
    valid_ids = [user_id for user_id, in valid_users.fetchall()]
    for user_id in valid_ids:
        db.add(ReminderAssignee(reminder_id=reminder_id, user_id=user_id))


@router.get("/reminders")
async def get_reminders(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    reminders = await _reminder_payloads(db, group.id, room_id=room_id)
    return {"reminders": reminders, "total": len(reminders)}


@router.post("/reminders")
async def create_reminder(
    request: ReminderCreateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    recurrence = _validated_recurrence(request.recurrence, request.recurrence_days)
    reminder_title = _reminder_title_from_request(request)
    if reminder_title is None:
        raise HTTPException(status_code=400, detail="Reminder title is required")
    reminder = Reminder(
        group_id=group.id,
        room_id=room_id,
        text=_clean_text(reminder_title, field="Reminder title", max_length=1000),
        context=(request.context or "").strip()[:2000] or None,
        due_at=_to_utc_naive(request.due_at),
        linked_event_id=request.linked_event_id,
        created_by_user_id=user.id,
        recurrence=recurrence,
        recurrence_days=request.recurrence_days if recurrence == "every_N_days" else None,
        recurrence_ends_at=_to_utc_naive(request.recurrence_ends_at) if request.recurrence_ends_at else None,
    )
    db.add(reminder)
    await db.flush()
    await _replace_reminder_assignees(db, reminder.id, request.assignee_user_ids)
    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="reminder",
        source_id=reminder.id,
        title=reminder.text[:220],
        body=reminder.context,
        status=_hub_item_status_from_legacy("reminder", is_completed=reminder.is_completed),
        created_by_user_id=user.id,
        assigned_to_user_id=request.assignee_user_ids[0] if request.assignee_user_ids else None,
        due_at=reminder.due_at,
        room_id=room_id,
    )
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.created, target_type="reminder", target_id=reminder.id, summary=f"{user.nickname} added reminder: {reminder.text[:80]}")
    await db.commit()
    return {"status": "created", "id": reminder.id}


@router.patch("/reminders/{reminder_id}")
async def update_reminder(
    reminder_id: int,
    request: ReminderUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    reminder = await db.get(Reminder, reminder_id)
    if not reminder or reminder.group_id != group.id or reminder.room_id != room_id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if not _can_manage_creator_owned_item(user, reminder.created_by_user_id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can edit this item")

    hub_item = await _load_hub_item_for_source(db, "reminder", reminder.id)
    current_tags = list(hub_item.tags or []) if hub_item else []

    before = {
        "text": reminder.text,
        "context": reminder.context,
        "due_at": reminder.due_at,
        "tags": _clean_tags(current_tags),
    }

    reminder_title = _reminder_title_from_request(request)
    if reminder_title is not None:
        reminder.text = _clean_text(reminder_title, field="Reminder title", max_length=1000)
    if _field_was_set(request, "context"):
        reminder.context = (request.context or "").strip()[:2000] or None
    if _field_was_set(request, "due_at"):
        reminder.due_at = _to_utc_naive(request.due_at) if request.due_at else None
    if _field_was_set(request, "linked_event_id"):
        reminder.linked_event_id = request.linked_event_id
    if _field_was_set(request, "recurrence"):
        reminder.recurrence = _validated_recurrence(request.recurrence, request.recurrence_days)
        reminder.recurrence_days = request.recurrence_days if reminder.recurrence == "every_N_days" else None
    if _field_was_set(request, "recurrence_ends_at"):
        reminder.recurrence_ends_at = _to_utc_naive(request.recurrence_ends_at) if request.recurrence_ends_at else None
    if request.assignee_user_ids is not None:
        await _replace_reminder_assignees(db, reminder.id, request.assignee_user_ids)
    assignee_id = None
    assignee_result = await db.execute(
        select(ReminderAssignee.user_id)
        .where(ReminderAssignee.reminder_id == reminder.id)
        .order_by(ReminderAssignee.id)
        .limit(1)
    )
    assignee_id = assignee_result.scalar_one_or_none()

    next_tags = current_tags
    if request.tags is not None:
        next_tags = list(request.tags)

    await _hub_item_for_source(
        db,
        group_id=group.id,
        item_type="reminder",
        source_id=reminder.id,
        title=reminder.text[:220],
        body=reminder.context,
        tags=next_tags,
        status=_hub_item_status_from_legacy("reminder", is_completed=reminder.is_completed),
        created_by_user_id=reminder.created_by_user_id,
        assigned_to_user_id=assignee_id,
        due_at=reminder.due_at,
        room_id=room_id,
    )
    after = {
        "text": reminder.text,
        "context": reminder.context,
        "due_at": reminder.due_at,
        "tags": _clean_tags(next_tags),
    }
    await _record_history(db, "reminder", reminder.id, user.id, before, after)
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.updated, target_type="reminder", target_id=reminder.id, summary=f"{user.nickname} updated reminder")
    await db.commit()
    return {"status": "updated"}


@router.post("/reminders/{reminder_id}/complete")
async def complete_reminder(
    reminder_id: int,
    request: ReminderCompleteRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    reminder = await db.get(Reminder, reminder_id)
    if not reminder or reminder.group_id != group.id or reminder.room_id != room_id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    reminder.is_completed = bool(request.is_completed)
    reminder.completed_at = datetime.utcnow() if reminder.is_completed else None
    reminder.completed_by_user_id = user.id if reminder.is_completed else None
    hub_item = (await db.execute(select(HubItem).where(
        HubItem.source_type == "reminder",
        HubItem.source_id == reminder.id,
        HubItem.room_id == room_id,
    ))).scalar_one_or_none()
    if hub_item:
        hub_item.status = _hub_item_status_from_legacy("reminder", is_completed=reminder.is_completed)
        hub_item.updated_at = datetime.utcnow()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.completed, target_type="reminder", target_id=reminder.id, summary=f"{user.nickname} {'completed' if reminder.is_completed else 'reopened'} reminder")
    await db.commit()
    return {"status": "updated"}


@router.delete("/reminders/{reminder_id}")
async def delete_reminder(
    reminder_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    reminder = await db.get(Reminder, reminder_id)
    if not reminder or reminder.group_id != group.id or reminder.room_id != room_id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if not _can_manage_creator_owned_item(user, reminder.created_by_user_id):
        raise HTTPException(status_code=403, detail="Only the creator or an admin can delete this item")
    hub_item = (await db.execute(select(HubItem).where(
        HubItem.source_type == "reminder",
        HubItem.source_id == reminder_id,
        HubItem.room_id == room_id,
    ))).scalar_one_or_none()
    if hub_item:
        hub_item.status = HubItemStatus.archived.value
        hub_item.pinned_to_home = False
        hub_item.updated_at = datetime.utcnow()
    else:
        await _hub_item_for_source(
            db,
            group_id=group.id,
            item_type="reminder",
            source_id=reminder.id,
            title=reminder.text[:220],
            body=reminder.context,
            status=HubItemStatus.archived.value,
            created_by_user_id=reminder.created_by_user_id,
            due_at=reminder.due_at,
            room_id=room_id,
        )
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.deleted, target_type="reminder", target_id=reminder_id, summary=f"{user.nickname} archived reminder")
    await db.commit()
    return {"status": "archived"}


@router.get("/comments")
async def get_comments(
    target_type: str,
    target_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    target = _validate_target_type(target_type)
    if not await _target_exists(db, target, target_id, group.id, room_id=room_id):
        return {"comments": [], "total": 0}
    result = await db.execute(
        select(Comment, User.id, User.username, User.nickname, User.role, User.avatar_url)
        .outerjoin(User, Comment.created_by_user_id == User.id)
        .where(Comment.group_id == group.id, Comment.target_type == target, Comment.target_id == target_id)
        .order_by(Comment.created_at.asc())
    )
    comments = [
        {
            "id": comment.id,
            "target_type": comment.target_type,
            "target_id": comment.target_id,
            "content": comment.content,
            "creator": _user_payload_from_row(user_id, username, nickname, role, avatar_url),
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
        }
        for comment, user_id, username, nickname, role, avatar_url in result.fetchall()
    ]
    reactions = await _reaction_summary(db, "comment", [comment["id"] for comment in comments])
    for comment in comments:
        comment["reactions"] = reactions.get(comment["id"], [])
    return {"comments": comments, "total": len(comments)}


@router.post("/comments")
async def create_comment(
    request: CommentCreateRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    target = _validate_target_type(request.target_type)
    if not await _target_exists(db, target, request.target_id, group.id, room_id=room_id):
        raise HTTPException(status_code=404, detail="Target not found")
    comment = Comment(
        group_id=group.id,
        target_type=target,
        target_id=request.target_id,
        content=_clean_text(request.content, field="Comment", max_length=1200),
        created_by_user_id=user.id,
    )
    db.add(comment)
    await db.flush()
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.commented, target_type=target, target_id=request.target_id, summary=f"{user.nickname} commented on {target}")
    await db.commit()
    background_tasks.add_task(
        _bg_comment_notification,
        user.id, user.nickname, comment.target_type, comment.target_id, manager
    )
    return {"status": "created", "id": comment.id}


@router.patch("/comments/{comment_id}")
async def update_comment(
    comment_id: int,
    request: CommentUpdateRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    comment = await db.get(Comment, comment_id)
    if not comment or comment.group_id != group.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    target = _validate_target_type(comment.target_type)
    if not await _target_exists(db, target, comment.target_id, group.id, room_id=room_id):
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.created_by_user_id and comment.created_by_user_id != user.id and user.role.value != "owner":
        raise HTTPException(status_code=403, detail="Not allowed to edit this comment")
    comment.content = _clean_text(request.content, field="Comment", max_length=1200)
    await db.commit()
    return {"status": "updated"}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    comment = await db.get(Comment, comment_id)
    if not comment or comment.group_id != group.id:
        raise HTTPException(status_code=404, detail="Comment not found")
    target = _validate_target_type(comment.target_type)
    if not await _target_exists(db, target, comment.target_id, group.id, room_id=room_id):
        raise HTTPException(status_code=404, detail="Comment not found")
    if comment.created_by_user_id and comment.created_by_user_id != user.id and user.role.value != "owner":
        raise HTTPException(status_code=403, detail="Not allowed to delete this comment")
    await db.delete(comment)
    await db.commit()
    return {"status": "deleted"}


@router.post("/reactions/toggle")
async def toggle_reaction(
    request: ReactionToggleRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    target = _validate_target_type(request.target_type)
    emoji = _clean_text(request.emoji, field="Emoji", max_length=10)
    if not await _target_exists(db, target, request.target_id, group.id, room_id=room_id):
        raise HTTPException(status_code=404, detail="Target not found")
    existing_result = await db.execute(
        select(Reaction).where(
            Reaction.target_type == target,
            Reaction.target_id == request.target_id,
            Reaction.user_id == user.id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing and existing.emoji == emoji:
        await db.delete(existing)
        status = "removed"
    elif existing:
        existing.emoji = emoji
        status = "updated"
    else:
        db.add(Reaction(target_type=target, target_id=request.target_id, user_id=user.id, user_session_id=user.session_id, emoji=emoji))
        status = "added"
    await _log_activity(db, group_id=group.id, actor_user_id=user.id, action=ActivityAction.reacted, target_type=target, target_id=request.target_id, summary=f"{user.nickname} reacted to {target}")
    await db.commit()
    return {"status": status}


@router.get("/reactions/{target_type}/{target_id}")
async def get_reaction_details(
    target_type: str,
    target_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Return who reacted to an item, grouped by emoji."""
    target = target_type.strip().lower()
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    if target == "message":
        target_result = await db.execute(
            select(Message.id).where(
                Message.id == target_id,
                Message.group_id == group.id,
                Message.room_id == room_id,
            )
        )
        if target_result.scalar_one_or_none() is None:
            return {"reactions": []}
        result = await db.execute(
            select(Reaction.emoji, User.nickname, User.username, User.avatar_url)
            .outerjoin(User, Reaction.user_session_id == User.session_id)
            .where(Reaction.message_id == target_id)
            .order_by(Reaction.emoji, User.nickname)
        )
    else:
        target = _validate_target_type(target)
        if not await _target_exists(db, target, target_id, group.id, room_id=room_id):
            return {"reactions": []}
        result = await db.execute(
            select(Reaction.emoji, User.nickname, User.username, User.avatar_url)
            .outerjoin(User, Reaction.user_id == User.id)
            .where(Reaction.target_type == target, Reaction.target_id == target_id)
            .order_by(Reaction.emoji, User.nickname)
        )
    grouped: dict[str, list] = {}
    for emoji, nickname, username, avatar_url in result.fetchall():
        grouped.setdefault(emoji, []).append({
            "nickname": nickname or "Unknown",
            "username": username,
            "avatar_url": avatar_url,
        })
    return {
        "reactions": [
            {"emoji": emoji, "users": users}
            for emoji, users in grouped.items()
        ]
    }


@router.get("/notifications")
async def get_notifications(
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    limit: int = 30,
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == user.id,
            or_(Notification.room_id == room_id, Notification.room_id.is_(None)),
        )
        .order_by(desc(Notification.created_at))
        .limit(limit)
    )
    notifications = result.scalars().all()
    unread_count = sum(1 for n in notifications if not n.is_read)
    return {
        "notifications": [
            {
                "id": n.id, "type": n.type, "title": n.title, "body": n.body,
                "target_type": n.target_type, "target_id": n.target_id,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "unread_count": unread_count,
    }


@router.patch("/notifications/read-all")
async def mark_all_notifications_read(
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read.is_(False),
            or_(Notification.room_id == room_id, Notification.room_id.is_(None)),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


@router.patch("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    await db.execute(
        update(Notification)
        .where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
            or_(Notification.room_id == room_id, Notification.room_id.is_(None)),
        )
        .values(is_read=True)
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/stats")
async def get_stats(
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Aggregate group statistics for the dashboard."""
    from datetime import timedelta, date as date_type
    from sqlalchemy import extract, cast, Date
    from app.domains.stats.service import StatsService
    from app.models.message import Message

    await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )

    # ── Yapometer — messages per user ────────────────────────────────────────
    msg_rows = (await db.execute(
        select(User.nickname, func.count(Message.id).label("n"))
        .join(Message, Message.user_session_id == User.session_id)
        .where(Message.is_deleted.is_(False), Message.room_id == room_id)
        .group_by(User.nickname)
        .order_by(desc("n"))
        .limit(10)
    )).fetchall()

    # ── Activity timeline — actions per day (last 30 days) ───────────────────
    thirty_ago = datetime.utcnow() - timedelta(days=29)
    act_rows = (await db.execute(
        select(cast(ActivityLog.created_at, Date).label("day"), func.count(ActivityLog.id).label("n"))
        .where(ActivityLog.created_at >= thirty_ago, ActivityLog.group_id == group.id)
        .group_by("day")
        .order_by("day")
    )).fetchall()
    act_map = {str(r.day): r.n for r in act_rows}
    today = datetime.utcnow().date()
    activity_timeline = [
        {"date": str(today - timedelta(days=29 - i)),
         "count": act_map.get(str(today - timedelta(days=29 - i)), 0)}
        for i in range(30)
    ]

    # ── Peak hours — message distribution by hour ────────────────────────────
    hour_rows = (await db.execute(
        select(extract("hour", Message.created_at).label("h"), func.count(Message.id).label("n"))
        .where(Message.is_deleted.is_(False), Message.room_id == room_id)
        .group_by("h")
        .order_by("h")
    )).fetchall()
    hour_map = {int(r.h): r.n for r in hour_rows}
    peak_hours = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    # ── Peak hour heatmap — message distribution by weekday and hour ─────────
    day_hour_rows = (await db.execute(
        select(
            extract("dow", Message.created_at).label("dow"),
            extract("hour", Message.created_at).label("h"),
            func.count(Message.id).label("n"),
        )
        .where(Message.is_deleted.is_(False), Message.room_id == room_id)
        .group_by("dow", "h")
        .order_by("dow", "h")
    )).fetchall()
    day_hour_map = {(int(r.dow), int(r.h)): r.n for r in day_hour_rows}
    peak_day_hours = [
        {
            "day": dow,
            "hours": [
                {"hour": h, "count": day_hour_map.get((dow, h), 0)}
                for h in range(24)
            ],
        }
        for dow in range(7)
    ]

    # ── Top reactions — emoji counts across all content ──────────────────────
    emoji_rows = (await db.execute(
        select(Reaction.emoji, func.count(Reaction.id).label("n"))
        .select_from(Reaction)
        .join(Message, Reaction.message_id == Message.id)
        .where(Message.room_id == room_id, Message.is_deleted.is_(False))
        .group_by(Reaction.emoji)
        .order_by(desc("n"))
        .limit(10)
    )).fetchall()

    # ── Idea status breakdown ────────────────────────────────────────────────
    idea_rows = (await db.execute(
        select(Idea.status, func.count(Idea.id).label("n"))
        .where(Idea.group_id == group.id, Idea.room_id == room_id)
        .group_by(Idea.status)
    )).fetchall()

    # ── Poll participation — distinct polls voted by each member ─────────────
    poll_part_rows = (await db.execute(
        select(User.nickname, func.count(func.distinct(PollVote.poll_id)).label("n"))
        .join(PollVote, PollVote.user_id == User.id)
        .join(Poll, Poll.id == PollVote.poll_id)
        .where(Poll.room_id == room_id)
        .group_by(User.nickname)
        .order_by(desc("n"))
        .limit(10)
    )).fetchall()

    # ── Overall totals ───────────────────────────────────────────────────────
    def _count(model, extra=None):
        stmt = select(func.count(model.id))
        if extra is not None:
            stmt = stmt.where(extra)
        return stmt

    first_message_at = (await db.execute(
        select(func.min(Message.created_at))
        .where(Message.is_deleted.is_(False), Message.room_id == room_id)
    )).scalar_one_or_none()
    if first_message_at and first_message_at.tzinfo is not None:
        first_message_at = first_message_at.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.utcnow()
    uptime_seconds = max(int((now - first_message_at).total_seconds()), 0) if first_message_at else 0
    uptime_days = max(uptime_seconds / 86400, 1) if first_message_at else 0

    totals_queries = {
        "messages":  _count(Message, (Message.is_deleted.is_(False)) & (Message.room_id == room_id)),
        "ideas":     _count(Idea, (Idea.group_id == group.id) & (Idea.room_id == room_id)),
        "polls":     _count(Poll, (Poll.group_id == group.id) & (Poll.room_id == room_id)),
        "reminders": _count(Reminder, (Reminder.group_id == group.id) & (Reminder.room_id == room_id)),
        "comments":  _count(Comment, Comment.group_id == group.id),
        "photos":    _count(Photo, (Photo.room_id == room_id) & (Photo.deleted_at.is_(None)) & (Photo.content_type != "image/gif")),
        "gifs":      _count(Photo, (Photo.room_id == room_id) & (Photo.deleted_at.is_(None)) & (Photo.content_type == "image/gif")),
    }
    totals = {}
    for key, stmt in totals_queries.items():
        totals[key] = (await db.execute(stmt)).scalar_one() or 0
    stats_service = StatsService(db)
    totals["members"] = await stats_service._room_member_count(room_id)
    totals["imported_members"] = await stats_service._imported_member_count(room_id)
    has_audio_files = (await db.execute(
        select(func.to_regclass("public.audio_files").is_not(None))
    )).scalar_one()
    totals["voice_notes"] = (
        (await db.execute(_count(AudioFile, AudioFile.room_id == room_id))).scalar_one() or 0
        if has_audio_files
        else 0
    )
    totals["reactions"] = (await db.execute(
        select(func.count(Reaction.id))
        .join(Message, Reaction.message_id == Message.id)
        .where(Message.room_id == room_id, Message.is_deleted.is_(False))
    )).scalar_one() or 0

    per_day_keys = ("messages", "photos", "gifs", "voice_notes", "reactions")
    per_day = {
        key: round(totals[key] / uptime_days, 2) if uptime_days else 0
        for key in per_day_keys
    }

    return {
        "yapometer":        [{"nickname": r.nickname, "count": r.n} for r in msg_rows],
        "activity_timeline": activity_timeline,
        "peak_hours":       peak_hours,
        "peak_day_hours":   peak_day_hours,
        "top_reactions":    [{"emoji": r.emoji, "count": r.n} for r in emoji_rows],
        "idea_status":      {r.status.value: r.n for r in idea_rows},
        "poll_participation": [{"nickname": r.nickname, "votes": r.n} for r in poll_part_rows],
        "totals":           totals,
        "first_message_at":  first_message_at.isoformat() if first_message_at else None,
        "uptime_seconds":    uptime_seconds,
        "per_day":           per_day,
    }


@router.get("/search")
async def search_content(
    q: str,
    types: str = "people,ideas,polls,events,reminders,notes,comments,messages",
    limit: int | None = None,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Full-text search across all content types."""
    user = await _current_user_or_401(authorization, db, session_cookie)
    q = q.strip()
    if len(q) < 2:
        raise HTTPException(status_code=400, detail="Query must be at least 2 characters")

    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    want = {t.strip().lower() for t in types.split(",") if t.strip()}
    pat = f"%{q}%"
    results: dict = {}

    def _row_date(val) -> str | None:
        return val.isoformat() if val else None

    def _attach_search_hub_metadata(payload: dict, metadata: dict | None) -> dict:
        return _apply_hub_metadata(payload, metadata) if metadata else payload

    search_limit = max(1, limit) if limit is not None else None

    def _with_search_limit(stmt):
        return stmt.limit(search_limit) if search_limit is not None else stmt

    if "ideas" in want:
        rows = (await db.execute(
            _with_search_limit(select(Idea, User.nickname)
            .outerjoin(User, Idea.created_by_user_id == User.id)
            .where(Idea.group_id == group.id, Idea.room_id == room_id, or_(
                Idea.title.ilike(pat), Idea.description.ilike(pat), Idea.category.ilike(pat),
            ))
            .order_by(desc(Idea.created_at)))
        )).fetchall()
        hub_items = await _hub_item_metadata_for_sources(db, "idea", [i.id for i, _ in rows], room_id=room_id)
        results["ideas"] = [
            _attach_search_hub_metadata({"id": i.id, "type": "idea", "title": i.title,
             "snippet": (i.description or i.category or "")[:160],
             "status": i.status.value if i.status else "maybe",
             "author": n or "Friend", "route": "/ideas",
             "created_at": _row_date(i.created_at)}, hub_items.get(i.id))
            for i, n in rows
        ]

    if "polls" in want:
        rows = (await db.execute(
            _with_search_limit(select(Poll, User.nickname)
            .outerjoin(User, Poll.created_by_user_id == User.id)
            .where(Poll.group_id == group.id, Poll.room_id == room_id, Poll.question.ilike(pat))
            .order_by(desc(Poll.created_at)))
        )).fetchall()
        hub_items = await _hub_item_metadata_for_sources(db, "poll", [p.id for p, _ in rows], room_id=room_id)
        results["polls"] = [
            _attach_search_hub_metadata({"id": p.id, "type": "poll", "title": p.question,
             "snippet": "", "author": n or "Friend", "route": "/polls",
             "created_at": _row_date(p.created_at)}, hub_items.get(p.id))
            for p, n in rows
        ]

    if "events" in want:
        rows = (await db.execute(
            _with_search_limit(select(Event, User.nickname)
            .outerjoin(User, Event.created_by_session_id == User.session_id)
            .where(
                Event.group_id == group.id,
                Event.room_id == room_id,
                Event.archived_at.is_(None),
                or_(
                    Event.title.ilike(pat), Event.description.ilike(pat), Event.location.ilike(pat),
                ),
            )
            .order_by(desc(Event.starts_at)))
        )).fetchall()
        hub_items = await _hub_item_metadata_for_sources(db, "event", [e.id for e, _ in rows], room_id=room_id)
        results["events"] = [
            _attach_search_hub_metadata({"id": e.id, "type": "event", "title": e.title,
             "snippet": (e.description or e.location or "")[:160],
             "author": n or "Friend", "route": f"/events/{e.id}",
             "created_at": _row_date(e.starts_at)}, hub_items.get(e.id))
            for e, n in rows
        ]

    if "reminders" in want:
        rows = (await db.execute(
            _with_search_limit(select(Reminder, User.nickname)
            .outerjoin(User, Reminder.created_by_user_id == User.id)
            .where(Reminder.group_id == group.id, Reminder.room_id == room_id, Reminder.text.ilike(pat))
            .order_by(desc(Reminder.created_at)))
        )).fetchall()
        hub_items = await _hub_item_metadata_for_sources(db, "reminder", [r.id for r, _ in rows], room_id=room_id)
        results["reminders"] = [
            _attach_search_hub_metadata({"id": r.id, "type": "reminder", "title": r.text[:120],
             "snippet": "", "author": n or "Friend", "route": "/reminders",
             "created_at": _row_date(r.created_at)}, hub_items.get(r.id))
            for r, n in rows
        ]

    if "notes" in want:
        rows = (await db.execute(
            _with_search_limit(select(Note, User.nickname)
            .outerjoin(User, Note.created_by_user_id == User.id)
            .where(
                Note.room_id == room_id,
                Note.archived_at.is_(None),
                or_(Note.title.ilike(pat), Note.body.ilike(pat), Note.note_type.ilike(pat)),
            )
            .order_by(desc(Note.updated_at)))
        )).fetchall()
        hub_items = await _hub_item_metadata_for_sources(db, "note", [n_.id for n_, _ in rows], room_id=room_id)
        results["notes"] = [
            _attach_search_hub_metadata({"id": note.id, "type": "note", "title": note.title,
             "snippet": (note.body or note.note_type or "")[:160],
             "author": nickname or "Friend", "route": f"/notes/{note.id}",
             "created_at": _row_date(note.updated_at)}, hub_items.get(note.id))
            for note, nickname in rows
        ]

    if "comments" in want:
        rows = (await db.execute(
            _with_search_limit(select(Comment, User.nickname)
            .outerjoin(User, Comment.created_by_user_id == User.id)
            .where(Comment.group_id == group.id, Comment.content.ilike(pat))
            .order_by(desc(Comment.created_at)))
        )).fetchall()
        route_map = {"idea": "/ideas", "poll": "/polls", "event": "/events", "reminder": "/reminders", "note": "/notes"}
        comment_hub_items: dict[tuple[str, int], dict] = {}
        for source_type in {"idea", "poll", "event", "reminder", "note"}:
            source_ids = [c.target_id for c, _ in rows if c.target_type == source_type]
            source_hub_items = await _hub_item_metadata_for_sources(db, source_type, source_ids, room_id=room_id)
            comment_hub_items.update({(source_type, source_id): item for source_id, item in source_hub_items.items()})
        rows = [
            (c, n)
            for c, n in rows
            if c.target_type not in route_map or comment_hub_items.get((c.target_type, c.target_id))
        ]
        results["comments"] = [
            _attach_search_hub_metadata({"id": c.id, "type": "comment",
             "title": f"Comment on {c.target_type}",
             "snippet": c.content[:160],
             "author": n or "Friend",
             "route": route_map.get(c.target_type, "/chat"),
             "created_at": _row_date(c.created_at)}, comment_hub_items.get((c.target_type, c.target_id)))
            for c, n in rows
        ]

    if "people" in want:
        from app.domains.members.service import MemberService

        members = await MemberService(db).get_members(include_bots=False, room_id=room_id)
        ql = q.lower()
        people_entries = []
        for m in members:
            if m.get("invite_pending"):
                continue
            nickname = m.get("nickname") or ""
            username = m.get("username") or ""
            display_role = m.get("display_role") or ""
            if not (ql in nickname.lower() or ql in username.lower() or ql in display_role.lower()):
                continue
            snippet_bits = []
            if username:
                snippet_bits.append(f"@{username}")
            if display_role:
                snippet_bits.append(display_role)
            people_entries.append({
                "id": m.get("session_id"),
                "type": "person",
                "title": nickname or username or "Member",
                "snippet": " · ".join(snippet_bits),
                "route": f"/profile/{username}" if username else None,
                "avatar_url": m.get("avatar_url"),
                "avatar_emoji": m.get("avatar_emoji"),
                "created_at": None,
            })
        if search_limit is not None:
            people_entries = people_entries[:search_limit]
        results["people"] = people_entries

    if "messages" in want:
        from app.models.message import Message
        from app.domains.ai.date_parsing import parse_explicit_date

        # Date queries ("1 June 2025") list that day's messages instead of ILIKE
        date_match = parse_explicit_date(q, datetime.utcnow())
        if date_match:
            message_where = (
                Message.is_deleted.is_(False),
                Message.room_id == room_id,
                Message.created_at >= date_match.day_start,
                Message.created_at < date_match.day_end,
            )
            message_order = Message.created_at.asc()
        else:
            message_where = (
                Message.content.ilike(pat),
                Message.is_deleted.is_(False),
                Message.room_id == room_id,
            )
            message_order = desc(Message.created_at)
        rows = (await db.execute(
            _with_search_limit(select(Message, User.nickname)
            .outerjoin(User, Message.user_session_id == User.session_id)
            .where(*message_where)
            .order_by(message_order))
        )).fetchall()
        message_hub_ids = [m.hub_item_id for m, _ in rows if m.hub_item_id is not None]
        message_hub_items = {}
        if message_hub_ids:
            hub_rows = (await db.execute(select(HubItem).where(HubItem.id.in_(message_hub_ids), HubItem.room_id == room_id))).scalars().all()
            message_hub_items = {item.id: _hub_item_payload(item) for item in hub_rows}
        message_entries = [
            _attach_search_hub_metadata({"id": m.id, "type": "message",
             "title": n or "Friend",
             "snippet": m.content[:160],
             "author": n or "Friend", "route": "/chat",
             "created_at": _row_date(m.created_at)}, message_hub_items.get(m.hub_item_id))
            for m, n in rows
        ]

        # Semantic leg: vector hits over message batches, ranked first.
        # Falls through silently when embeddings are disabled/missing.
        if not date_match:
            try:
                from app.domains.ai.retrieval import ChatRetrievalService

                retrieval = ChatRetrievalService(db)
                if await retrieval.has_embeddings(room_id):
                    seen_message_ids = {entry["id"] for entry in message_entries}
                    semantic_entries = []
                    for src in await retrieval.retrieve_semantic(
                        q, room_id, source_types=("message_batch",)
                    ):
                        if src.message_start_id is None or src.message_start_id in seen_message_ids:
                            continue
                        seen_message_ids.add(src.message_start_id)
                        semantic_entries.append({
                            "id": src.message_start_id,
                            "type": "message",
                            "title": src.title,
                            "snippet": src.text[:160],
                            "author": "Chat",
                            "route": "/chat",
                            "created_at": None,
                            "score": src.score,
                        })
                    message_entries = semantic_entries + message_entries
                    if search_limit is not None:
                        message_entries = message_entries[:search_limit]
            except Exception:
                logging.getLogger(__name__).warning(
                    "Semantic search leg failed; using keyword results", exc_info=True
                )

        results["messages"] = message_entries

    return {"query": q, "results": results, "total": sum(len(v) for v in results.values())}


_SEARCH_ASK_FILTERS = {
    "all",
    "messages",
    "polls",
    "events",
    "photos",
    "people",
    "ideas",
    "reminders",
    "notes",
    "comments",
    "references",
}


def _search_ask_route(source_type: str, source_id: str | int) -> str | None:
    routes = {
        "messages": f"/chat?message={source_id}",
        "polls": "/polls",
        "events": f"/events/{source_id}",
        "photos": "/photos",
        "ideas": "/ideas",
        "reminders": "/reminders",
        "notes": f"/notes/{source_id}",
        "comments": None,
    }
    return routes.get(source_type)


def _search_ask_reference(source_type: str, source_id: str | int) -> str | None:
    prefix = {"polls": "P", "events": "E", "reminders": "R", "notes": "N"}.get(source_type)
    return f"#{prefix}-{source_id}" if prefix else None


async def _validated_search_ask_source(
    db: AsyncSession,
    group: Group,
    hint: SearchAskVisibleResult,
    room_id=None,
) -> SearchAskSource | None:
    source_type = normalize_source_type(hint.type)
    raw_id = str(hint.id).strip()
    if not source_type or not raw_id:
        return None

    if source_type == "references":
        ref = str(hint.reference or raw_id).strip()
        refs = find_hub_item_references(ref)
        if not refs:
            return None
        hub_item = (await db.execute(
            select(HubItem).where(
                HubItem.group_id == group.id,
                func.upper(HubItem.short_id) == refs[0]["short_id"].upper(),
                HubItem.archived_at.is_(None),
                HubItem.status != HubItemStatus.archived.value,
                *( [HubItem.room_id == room_id] if room_id is not None else [] ),
            )
        )).scalar_one_or_none()
        if not hub_item:
            return None
        source_type = f"{hub_item.source_type or hub_item.item_type}s"
        raw_id = str(hub_item.source_id or hub_item.id)

    try:
        numeric_id = int(raw_id)
    except (TypeError, ValueError):
        return None

    item = None
    title = ""
    snippet = ""
    author = None
    created_at = None

    if source_type == "messages":
        row = (await db.execute(
            select(Message, User.nickname)
            .outerjoin(User, Message.user_session_id == User.session_id)
            .where(
                Message.id == numeric_id,
                Message.is_deleted.is_(False),
                *( [Message.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = author or "Message"
        snippet = item.content
        created_at = item.created_at

    elif source_type == "polls":
        row = (await db.execute(
            select(Poll, User.nickname)
            .outerjoin(User, Poll.created_by_user_id == User.id)
            .where(
                Poll.id == numeric_id,
                Poll.group_id == group.id,
                Poll.archived_at.is_(None),
                *( [Poll.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = item.question
        snippet = f"Poll status: {item.status or 'open'}"
        created_at = item.created_at

    elif source_type == "events":
        row = (await db.execute(
            select(Event, User.nickname)
            .outerjoin(User, Event.created_by_session_id == User.session_id)
            .where(
                Event.id == numeric_id,
                Event.group_id == group.id,
                Event.archived_at.is_(None),
                *( [Event.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = item.title
        detail_bits = [item.description, item.location]
        snippet = " | ".join(bit for bit in detail_bits if bit)
        created_at = item.starts_at

    elif source_type == "ideas":
        row = (await db.execute(
            select(Idea, User.nickname)
            .outerjoin(User, Idea.created_by_user_id == User.id)
            .where(
                Idea.id == numeric_id,
                Idea.group_id == group.id,
                Idea.archived_at.is_(None),
                *( [Idea.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = item.title
        snippet = item.description or item.category or ""
        created_at = item.created_at

    elif source_type == "reminders":
        row = (await db.execute(
            select(Reminder, User.nickname)
            .outerjoin(User, Reminder.created_by_user_id == User.id)
            .where(
                Reminder.id == numeric_id,
                Reminder.group_id == group.id,
                Reminder.archived_at.is_(None),
                *( [Reminder.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = item.text[:120]
        snippet = "Completed" if item.is_completed else "Open reminder"
        created_at = item.created_at

    elif source_type == "notes":
        row = (await db.execute(
            select(Note, User.nickname)
            .outerjoin(User, Note.created_by_user_id == User.id)
            .where(
                Note.id == numeric_id,
                Note.archived_at.is_(None),
                *( [Note.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = item.title
        snippet = item.body or item.note_type or ""
        created_at = item.updated_at

    elif source_type == "comments":
        row = (await db.execute(
            select(Comment, User.nickname)
            .outerjoin(User, Comment.created_by_user_id == User.id)
            .where(Comment.id == numeric_id, Comment.group_id == group.id)
        )).first()
        if not row:
            return None
        item, author = row
        title = f"Comment on {item.target_type}"
        snippet = item.content
        created_at = item.created_at

    elif source_type == "photos":
        row = (await db.execute(
            select(Photo, User.nickname)
            .outerjoin(User, Photo.uploaded_by_session_id == User.session_id)
            .where(
                Photo.id == numeric_id,
                *( [Photo.room_id == room_id] if room_id is not None else [] ),
            )
        )).first()
        if not row:
            return None
        item, author = row
        title = item.caption or item.original_filename or "Photo"
        snippet = item.caption or "Photo result"
        created_at = item.created_at

    else:
        return None

    source_id = make_source_id(source_type, numeric_id)
    return SearchAskSource(
        source_id=source_id,
        type=source_type,
        id=str(numeric_id),
        title=truncate_text(title, 160),
        snippet=truncate_text(snippet, MAX_SNIPPET_CHARS),
        route=_search_ask_route(source_type, numeric_id),
        reference=_search_ask_reference(source_type, numeric_id),
        author=author,
        created_at=created_at.isoformat() if created_at else None,
    )


async def _validate_search_ask_sources(
    db: AsyncSession,
    group: Group,
    visible_results: list[SearchAskVisibleResult],
    room_id=None,
) -> list[SearchAskSource]:
    validated: list[SearchAskSource] = []
    seen: set[str] = set()
    for hint in visible_results[:MAX_SOURCES]:
        source = await _validated_search_ask_source(db, group, hint, room_id=room_id)
        if not source or source.source_id in seen:
            continue
        seen.add(source.source_id)
        validated.append(source)
    return validated


@router.post("/search/ask", response_model=SearchAskResponse)
async def ask_search_hub_bot(
    request: SearchAskRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(status_code=400, detail=f"Question must be {MAX_QUESTION_CHARS} characters or fewer")
    if len(request.visible_results) > 24:
        raise HTTPException(status_code=400, detail="Too many visible results supplied")

    filters = [str(f).strip().lower() for f in request.filters if str(f).strip()]
    unknown_filters = [f for f in filters if f not in _SEARCH_ASK_FILTERS]
    if unknown_filters:
        raise HTTPException(status_code=400, detail=f"Unsupported filters: {', '.join(unknown_filters)}")

    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    sources = await _validate_search_ask_sources(db, group, request.visible_results, room_id=room_id)
    service = SearchAskService(db)
    result = await service.ask(
        question=question,
        search_query=truncate_text(request.search_query, 240),
        filters=filters,
        sources=sources,
        user_id=str(user.id),
    )

    return SearchAskResponse(
        answer=result.answer,
        sources=[SearchAskSourceResponse(**source.to_payload()) for source in result.sources],
        request_id=result.request_id,
    )


def _photo_payload(
    photo: Photo,
    nickname: str | None = None,
    message_id: int | None = None,
    *,
    is_cover: bool = False,
    uploaded_by_session_id=None,
    original_sender: str | None = None,
) -> dict:
    return {
        "id": photo.id,
        "url": f"/uploads/photos/{photo.filename}",
        "thumbnail_url": f"/uploads/photos/{photo.thumbnail_filename}" if photo.thumbnail_filename else f"/uploads/photos/{photo.filename}",
        "filename": photo.filename,
        "original_filename": photo.original_filename,
        "content_type": photo.content_type,
        "size_bytes": photo.size_bytes,
        "width": photo.width,
        "height": photo.height,
        "caption": photo.caption,
        "tags": photo.tags or [],
        "event_id": getattr(photo, "event_id", None),
        "hub_item_id": str(photo.hub_item_id) if getattr(photo, "hub_item_id", None) else None,
        "uploaded_by": nickname,
        "uploaded_by_session_id": str(uploaded_by_session_id or photo.uploaded_by_session_id) if (uploaded_by_session_id or getattr(photo, "uploaded_by_session_id", None)) else None,
        "is_cover": is_cover,
        "source_type": getattr(photo, "source_type", None) or "manual_upload",
        "taken_at": photo.taken_at.isoformat() if getattr(photo, "taken_at", None) else None,
        "original_sender": original_sender,
        "created_at": photo.created_at.isoformat() if photo.created_at else None,
        "deleted_at": photo.deleted_at.isoformat() if getattr(photo, "deleted_at", None) else None,
        "message_id": message_id,
    }


def _photo_list_filters(
    room_id,
    *,
    hub_item_id: str | None = None,
    event_id: int | None = None,
    tag: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    source_type: str | None = None,
    sender: str | None = None,
) -> list:
    """Shared WHERE clauses for photo listing queries. Queries using the
    sender filter must outerjoin User on uploaded_by_session_id."""
    filters = [Photo.deleted_at.is_(None), Photo.room_id == room_id]
    if hub_item_id is not None:
        filters.append(Photo.hub_item_id == hub_item_id)
    elif event_id is not None:
        filters.append(Photo.event_id == event_id)
    if tag is not None:
        normalized_tag = tag.strip().lower().lstrip("#")
        filters.append(
            text("photos.tags::jsonb @> CAST(:tag_json AS jsonb)").bindparams(
                tag_json=json.dumps([normalized_tag])
            )
        )
    # Date filters use the photo's display date (taken_at, else created_at) so
    # they line up with the month groups the UI renders.
    photo_date = func.coalesce(Photo.taken_at, Photo.created_at)
    if start_at is not None:
        filters.append(photo_date >= _to_utc_naive(start_at))
    if end_at is not None:
        filters.append(photo_date < _to_utc_naive(end_at) + timedelta(days=1))
    if source_type is not None:
        filters.append(Photo.source_type == source_type)
    if sender is not None:
        # The sender dropdown shows original_sender (imported raw name) falling
        # back to uploader nickname, so the filter must accept either.
        sender_pattern = f"%{sender}%"
        imported_sender_match = (
            select(ImportedMessageSource.id)
            .where(
                ImportedMessageSource.message_id == Photo.message_id,
                ImportedMessageSource.raw_sender_name.ilike(sender_pattern),
            )
            .exists()
        )
        filters.append(or_(User.nickname.ilike(sender_pattern), imported_sender_match))
    return filters


@router.get("/photos")
async def get_photos(
    limit: int = 60,
    offset: int = 0,
    tag: str | None = None,
    event_id: int | None = None,
    hub_item_id: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    source_type: str | None = None,
    sender: str | None = None,
    sort: str | None = None,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )

    # Determine sort column: "taken_asc"/"taken_desc" use taken_at (fallback created_at),
    # "uploaded" uses created_at (upload/import time). Default: newest first.
    # Photos posted together share timestamps, so id breaks ties — without it
    # offset pagination repeats/skips rows on tied timestamps.
    if sort == "oldest":
        order_col = Photo.taken_at.asc().nulls_last()
        order_fallback = Photo.created_at.asc()
        order_tiebreak = Photo.id.asc()
    elif sort == "uploaded":
        order_col = desc(Photo.created_at)
        order_fallback = None
        order_tiebreak = Photo.id.desc()
    else:  # "newest" or unset
        order_col = Photo.taken_at.desc().nulls_last()
        order_fallback = desc(Photo.created_at)
        order_tiebreak = Photo.id.desc()

    if order_fallback is not None:
        order_by = (order_col, order_fallback, order_tiebreak)
    else:
        order_by = (order_col, order_tiebreak)

    filters = _photo_list_filters(
        room_id,
        hub_item_id=hub_item_id,
        event_id=event_id,
        tag=tag,
        start_at=start_at,
        end_at=end_at,
        source_type=source_type,
        sender=sender,
    )

    query = (
        select(Photo, User.nickname)
        .outerjoin(User, Photo.uploaded_by_session_id == User.session_id)
        .where(*filters)
        .order_by(*order_by)
    )

    total = (await db.execute(
        select(func.count(Photo.id))
        .outerjoin(User, Photo.uploaded_by_session_id == User.session_id)
        .where(*filters)
    )).scalar_one() or 0

    result = await db.execute(query.limit(limit).offset(offset))
    rows = result.fetchall()

    # Map fetched photos to their chat messages. Newer imports store the link
    # on the photo row; older rows (pre message_id backfill) need the legacy
    # message-content scan.
    filename_to_message: dict[str, int] = {
        photo.filename: photo.message_id for photo, _ in rows if photo.message_id is not None
    }
    has_unlinked_imports = any(
        photo.message_id is None and photo.source_type == "messenger_import" for photo, _ in rows
    )
    if has_unlinked_imports:
        msg_result = await db.execute(
            select(Message.id, Message.content).where(
                Message.content.like("%/uploads/photos/%"),
                Message.room_id == room_id,
            )
        )
        for msg_id, content in msg_result.fetchall():
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("/uploads/photos/"):
                    fname = line.removeprefix("/uploads/photos/")
                    if fname not in filename_to_message:
                        filename_to_message[fname] = msg_id

    cover_photo_ids: set[int] = set()
    photo_hub_item_ids = {photo.hub_item_id for photo, _ in rows if photo.hub_item_id is not None}
    if photo_hub_item_ids:
        cover_rows = await db.execute(
            select(HubItem.cover_photo_id).where(HubItem.id.in_(photo_hub_item_ids))
        )
        cover_photo_ids = {row for row in cover_rows.scalars().all() if row is not None}

    # Batch-fetch original_sender from ImportedMessageSource for imported photos
    imported_msg_ids = [
        filename_to_message[photo.filename]
        for photo, _ in rows
        if photo.source_type == "messenger_import" and photo.filename in filename_to_message
    ]
    msg_id_to_sender: dict[int, str] = {}
    if imported_msg_ids:
        sender_rows = await db.execute(
            select(ImportedMessageSource.message_id, ImportedMessageSource.raw_sender_name)
            .where(ImportedMessageSource.message_id.in_(imported_msg_ids))
            .order_by(ImportedMessageSource.id)
        )
        # A message can have several source rows; keep the earliest deterministically
        for msg_id, raw_name in sender_rows.fetchall():
            msg_id_to_sender.setdefault(msg_id, raw_name)

    photos = [
        _photo_payload(
            photo,
            nickname,
            filename_to_message.get(photo.filename),
            is_cover=photo.id in cover_photo_ids,
            original_sender=msg_id_to_sender.get(filename_to_message.get(photo.filename)),
        )
        for photo, nickname in rows
    ]
    return {"photos": photos, "total": total, "offset": offset, "limit": limit}


@router.get("/photos/senders")
async def get_photo_senders(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Distinct sender names across all photos in the room, mirroring the
    per-photo display rule: imported original sender, else uploader nickname."""
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    imported_rows = await db.execute(
        select(ImportedMessageSource.raw_sender_name)
        .join(Photo, Photo.message_id == ImportedMessageSource.message_id)
        .where(Photo.deleted_at.is_(None), Photo.room_id == room_id)
        .distinct()
    )
    uploader_rows = await db.execute(
        select(User.nickname)
        .join(Photo, Photo.uploaded_by_session_id == User.session_id)
        .where(
            Photo.deleted_at.is_(None),
            Photo.room_id == room_id,
            or_(Photo.source_type != "messenger_import", Photo.message_id.is_(None)),
        )
        .distinct()
    )
    senders = {name for name in imported_rows.scalars().all() if name}
    senders.update(name for name in uploader_rows.scalars().all() if name)
    return {"senders": sorted(senders, key=str.lower)}


@router.get("/photos/months")
async def get_photo_months(
    tag: str | None = None,
    event_id: int | None = None,
    hub_item_id: str | None = None,
    source_type: str | None = None,
    sender: str | None = None,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Distinct calendar months ("YYYY-MM", newest first) that have photos
    matching the filters, so the month picker can cover unloaded pages."""
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    filters = _photo_list_filters(
        room_id,
        hub_item_id=hub_item_id,
        event_id=event_id,
        tag=tag,
        source_type=source_type,
        sender=sender,
    )
    month_expr = func.date_trunc("month", func.coalesce(Photo.taken_at, Photo.created_at))
    rows = await db.execute(
        select(month_expr)
        .outerjoin(User, Photo.uploaded_by_session_id == User.session_id)
        .where(*filters)
        .distinct()
        .order_by(month_expr.desc())
    )
    months = [month.strftime("%Y-%m") for month in rows.scalars().all() if month is not None]
    return {"months": months}


@router.post("/photos")
async def upload_photo(
    request: PhotoUploadRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    settings = get_settings()
    user = await _current_user_or_401(authorization, db, session_cookie)
    _ensure_not_demo_guest(user)
    if request.content_type and not request.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image uploads are supported")

    try:
        _, separator, encoded = request.data_url.partition(",")
        if not separator:
            raise ValueError("missing data URL separator")
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid image data") from exc

    if len(content) > settings.photo_max_upload_bytes:
        raise HTTPException(status_code=400, detail="Image is too large")

    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    photo_event = None
    hub_item: HubItem | None = None

    if request.hub_item_id is not None:
        hub_item = await db.get(HubItem, request.hub_item_id)
        if not hub_item or hub_item.group_id != group.id or hub_item.room_id != room_id:
            raise HTTPException(status_code=400, detail="Hub item does not exist")
        if hub_item.source_type == "event" and hub_item.source_id is not None:
            photo_event = await db.get(Event, hub_item.source_id)
            if photo_event and photo_event.room_id != room_id:
                raise HTTPException(status_code=400, detail="Event does not exist")

    if request.event_id is not None:
        photo_event = await db.get(Event, request.event_id)
        if not photo_event or photo_event.group_id != group.id or photo_event.room_id != room_id:
            raise HTTPException(status_code=400, detail="Event does not exist")
        if hub_item is None:
            hub_item_row = await db.execute(
                select(HubItem).where(
                    HubItem.source_type == "event",
                    HubItem.source_id == photo_event.id,
                    HubItem.room_id == room_id,
                )
            )
            hub_item = hub_item_row.scalar_one_or_none()

    tag_id = _optional_tag_id(request.tag_id) or (photo_event.photo_tag_id if photo_event else None)

    processed = process_photo_upload(
        content,
        display_max_width=settings.photo_display_max_width,
        thumbnail_max_width=settings.photo_thumbnail_max_width,
        jpeg_quality=settings.photo_jpeg_quality,
    )

    upload_dir = get_photo_upload_path()
    upload_dir.mkdir(parents=True, exist_ok=True)
    ensure_photo_storage_capacity(
        upload_dir,
        processed.total_size_bytes,
        settings.photo_storage_max_bytes,
    )

    photo_id = uuid.uuid4().hex
    filename = f"{photo_id}{processed.extension}"
    thumbnail_filename = f"{photo_id}_thumb{processed.extension}"
    display_path = upload_dir / filename
    thumbnail_path = upload_dir / thumbnail_filename
    display_path.write_bytes(processed.display_bytes)
    thumbnail_path.write_bytes(processed.thumbnail_bytes)

    clean_tags = _clean_tags(request.tags) if request.tags else []
    photo = Photo(
        filename=filename,
        thumbnail_filename=thumbnail_filename,
        original_filename=request.filename or filename,
        content_type=processed.content_type,
        size_bytes=processed.size_bytes,
        width=processed.width,
        height=processed.height,
        thumbnail_size_bytes=processed.thumbnail_size_bytes,
        caption=request.caption.strip()[:500] if request.caption else None,
        tags=clean_tags,
        event_id=photo_event.id if photo_event else None,
        hub_item_id=hub_item.id if hub_item else None,
        tag_id=tag_id,
        uploaded_by_session_id=user.session_id,
        room_id=room_id,
    )
    try:
        db.add(photo)
        await db.commit()
        await db.refresh(photo)
    except Exception:
        display_path.unlink(missing_ok=True)
        thumbnail_path.unlink(missing_ok=True)
        raise
    return {"photo": _photo_payload(photo)}


async def _photo_with_hub_item(
    db: AsyncSession, photo_id: int, room_id=None
) -> tuple[Photo, HubItem | None]:
    photo = await db.get(Photo, photo_id)
    if not photo or photo.deleted_at is not None or (room_id is not None and photo.room_id != room_id):
        raise HTTPException(status_code=404, detail="Photo not found")
    hub_item: HubItem | None = None
    if photo.hub_item_id is not None:
        hub_item = await db.get(HubItem, photo.hub_item_id)
        if hub_item is not None and room_id is not None and hub_item.room_id != room_id:
            hub_item = None
    elif photo.event_id is not None:
        row = await db.execute(
            select(HubItem).where(
                HubItem.source_type == "event",
                HubItem.source_id == photo.event_id,
                *( [HubItem.room_id == room_id] if room_id is not None else [] ),
            )
        )
        hub_item = row.scalar_one_or_none()
    return photo, hub_item


def _home_appearance_payload(record: HomeAppearance | None, photo: Photo | None) -> dict:
    if record is None:
        return {
            "cover_photo_id": None,
            "cover_photo_url": None,
            "cover_thumbnail_url": None,
            "cover_position_x": 50,
            "cover_position_y": 50,
            "overlay_strength": 50,
            "blur_enabled": False,
            "header_icon": None,
            "updated_at": None,
            "updated_by_user_id": None,
        }
    cover_url = f"/uploads/photos/{photo.filename}" if photo else None
    cover_thumb = (
        f"/uploads/photos/{photo.thumbnail_filename}"
        if photo and photo.thumbnail_filename
        else cover_url
    )
    return {
        "cover_photo_id": record.cover_photo_id,
        "cover_photo_url": cover_url,
        "cover_thumbnail_url": cover_thumb,
        "cover_position_x": record.cover_position_x if record.cover_position_x is not None else 50,
        "cover_position_y": record.cover_position_y if record.cover_position_y is not None else 50,
        "overlay_strength": record.overlay_strength if record.overlay_strength is not None else 50,
        "blur_enabled": bool(record.blur_enabled),
        "header_icon": record.header_icon,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "updated_by_user_id": str(record.updated_by_user_id) if record.updated_by_user_id else None,
    }


async def _get_or_create_home_appearance(db: AsyncSession, group_id: int) -> HomeAppearance:
    result = await db.execute(
        select(HomeAppearance).where(HomeAppearance.group_id == group_id)
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = HomeAppearance(group_id=group_id)
        db.add(record)
        await db.flush()
    return record


async def _home_appearance_with_photo(
    db: AsyncSession, record: HomeAppearance | None
) -> tuple[HomeAppearance | None, Photo | None]:
    if record is None or record.cover_photo_id is None:
        return record, None
    photo = await db.get(Photo, record.cover_photo_id)
    return record, photo


@router.get("/home-appearance")
async def get_home_appearance(db: AsyncSession = Depends(get_db_session)):
    group = await _default_group(db)
    result = await db.execute(
        select(HomeAppearance).where(HomeAppearance.group_id == group.id)
    )
    record = result.scalar_one_or_none()
    record, photo = await _home_appearance_with_photo(db, record)
    return {"appearance": _home_appearance_payload(record, photo)}


@router.put("/home-appearance")
async def update_home_appearance(
    request: HomeAppearanceUpdateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    record = await _get_or_create_home_appearance(db, group.id)

    if _field_was_set(request, "cover_photo_id"):
        if request.cover_photo_id is None:
            record.cover_photo_id = None
            record.cover_position_x = 50
            record.cover_position_y = 50
        else:
            photo = await db.get(Photo, request.cover_photo_id)
            if photo is None:
                raise HTTPException(status_code=400, detail="Photo does not exist")
            cover_changed = record.cover_photo_id != photo.id
            record.cover_photo_id = photo.id
            if cover_changed:
                record.cover_position_x = 50
                record.cover_position_y = 50

    if _field_was_set(request, "cover_position_x") and request.cover_position_x is not None:
        record.cover_position_x = max(0, min(100, int(request.cover_position_x)))
    if _field_was_set(request, "cover_position_y") and request.cover_position_y is not None:
        record.cover_position_y = max(0, min(100, int(request.cover_position_y)))
    if _field_was_set(request, "overlay_strength") and request.overlay_strength is not None:
        record.overlay_strength = max(0, min(100, int(request.overlay_strength)))
    if _field_was_set(request, "blur_enabled") and request.blur_enabled is not None:
        record.blur_enabled = bool(request.blur_enabled)
    if _field_was_set(request, "header_icon"):
        icon = (request.header_icon or "").strip()
        record.header_icon = icon[:40] if icon else None

    record.updated_by_user_id = user.id
    record.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(record)
    record, photo = await _home_appearance_with_photo(db, record)
    return {"appearance": _home_appearance_payload(record, photo)}


@router.post("/home-appearance/cover")
async def set_home_appearance_cover(
    request: HomeAppearanceSetCoverRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    photo = await db.get(Photo, request.photo_id)
    if photo is None:
        raise HTTPException(status_code=400, detail="Photo does not exist")
    record = await _get_or_create_home_appearance(db, group.id)
    cover_changed = record.cover_photo_id != photo.id
    record.cover_photo_id = photo.id
    if cover_changed:
        record.cover_position_x = 50
        record.cover_position_y = 50
    record.updated_by_user_id = user.id
    record.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(record)
    return {"appearance": _home_appearance_payload(record, photo)}


@router.delete("/home-appearance/cover")
async def remove_home_appearance_cover(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    result = await db.execute(
        select(HomeAppearance).where(HomeAppearance.group_id == group.id)
    )
    record = result.scalar_one_or_none()
    if record is None or record.cover_photo_id is None:
        return {"appearance": _home_appearance_payload(record, None)}
    record.cover_photo_id = None
    record.cover_position_x = 50
    record.cover_position_y = 50
    record.updated_by_user_id = user.id
    record.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(record)
    return {"appearance": _home_appearance_payload(record, None)}


@router.post("/photos/{photo_id}/cover")
async def set_photo_as_cover(
    photo_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    photo, hub_item = await _photo_with_hub_item(db, photo_id, room_id=room_id)
    if hub_item is None:
        raise HTTPException(status_code=400, detail="Photo is not attached to an item")

    if not await photo_permissions.can_set_cover(db, user, hub_item):
        raise HTTPException(
            status_code=403,
            detail="Only the item creator or admins can replace the cover",
        )

    cover_changed = hub_item.cover_photo_id != photo.id
    hub_item.cover_photo_id = photo.id
    if cover_changed:
        hub_item.cover_photo_position_x = 50
        hub_item.cover_photo_position_y = 50
    if hub_item.source_type == "event" and hub_item.source_id is not None:
        event_row = await db.get(Event, hub_item.source_id)
        if event_row is not None:
            event_row.cover_photo_url = f"/uploads/photos/{photo.filename}"
    await db.commit()
    return {"status": "ok", "photo_id": photo.id, "hub_item_id": str(hub_item.id)}


@router.patch("/hub-items/{item_id}/cover-position")
async def update_hub_item_cover_position(
    item_id: str,
    request: CoverPhotoPositionRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    group = await _default_group(db)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    hub_item = await _hub_item_by_id_or_404(db, group.id, item_id, room_id=room_id)

    if hub_item.cover_photo_id is None:
        raise HTTPException(status_code=400, detail="Item has no cover photo to position")

    if not await photo_permissions.can_set_cover(db, user, hub_item):
        raise HTTPException(
            status_code=403,
            detail="Only the item creator or admins can reposition the cover",
        )

    x = max(0, min(100, int(request.x)))
    y = max(0, min(100, int(request.y)))
    hub_item.cover_photo_position_x = x
    hub_item.cover_photo_position_y = y
    await db.commit()
    return {"status": "ok", "x": x, "y": y, "hub_item_id": str(hub_item.id)}


@router.delete("/photos/{photo_id}")
async def delete_photo(
    photo_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    photo, hub_item = await _photo_with_hub_item(db, photo_id, room_id=room_id)

    if not await photo_permissions.can_delete_photo(db, user, photo, hub_item):
        raise HTTPException(
            status_code=403,
            detail="Only the photo poster, item creator, or admins can delete this photo",
        )

    if hub_item is not None and hub_item.cover_photo_id == photo.id:
        hub_item.cover_photo_id = None
        if hub_item.source_type == "event" and hub_item.source_id is not None:
            event_row = await db.get(Event, hub_item.source_id)
            if event_row is not None:
                event_row.cover_photo_url = None

    upload_dir = get_photo_upload_path()
    display_path = upload_dir / photo.filename if photo.filename else None
    thumbnail_path = (
        upload_dir / photo.thumbnail_filename if photo.thumbnail_filename else None
    )

    photo.deleted_at = datetime.utcnow()
    photo.deleted_by_user_id = user.id
    await db.commit()

    if display_path is not None:
        display_path.unlink(missing_ok=True)
    if thumbnail_path is not None:
        thumbnail_path.unlink(missing_ok=True)
    return {"status": "deleted", "id": photo_id}


@router.get("/push/vapid-public-key")
async def get_vapid_public_key():
    """Return the VAPID public key the browser needs to subscribe.

    Public on purpose — the public key is meant to be distributed to clients.
    Returns 503 when push isn't configured so the frontend can hide the UI.
    """
    settings = get_settings()
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Push notifications not configured")
    return {"public_key": settings.vapid_public_key}


@router.post("/push/subscriptions")
async def create_push_subscription(
    request: PushSubscriptionRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Register (or refresh) a Web Push subscription for the current user.

    Accepts the session cookie as well as the bearer token: the service
    worker's `pushsubscriptionchange` handler re-registers rotated endpoints
    but has no access to the token in localStorage.
    """
    from app.domains.notifications.push_repository import PushSubscriptionRepository

    user = await _current_user_or_401(authorization, db, session_cookie)
    repo = PushSubscriptionRepository(db)
    await repo.upsert(
        user_id=user.id,
        endpoint=request.endpoint,
        p256dh_key=request.p256dh_key,
        auth_key=request.auth_key,
        user_agent=request.user_agent,
    )
    return {"status": "registered"}


@router.delete("/push/subscriptions")
async def delete_push_subscription(
    endpoint: str,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Unregister a Web Push subscription for the current user.

    Endpoint URL passed as a query string parameter (DELETE bodies are not
    portable across HTTP clients).
    """
    from app.domains.notifications.push_repository import PushSubscriptionRepository

    user = await _current_user_or_401(authorization, db, session_cookie)
    repo = PushSubscriptionRepository(db)
    deleted = await repo.delete_for_user(user_id=user.id, endpoint=endpoint)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "unregistered"}


@router.post("/push/test")
async def send_test_push(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Send a test push to the current user's subscriptions. For diagnostics."""
    from app.domains.notifications.push_fanout import fanout_push_to_user
    from app.domains.notifications.push_repository import PushSubscriptionRepository

    user = await _current_user_or_401(authorization, db, session_cookie)

    subs = await PushSubscriptionRepository(db).list_for_user(user.id)
    if not subs:
        raise HTTPException(status_code=404, detail="No active push subscriptions for this user")

    await fanout_push_to_user(
        db,
        user_id=user.id,
        notif_type="test",
        title="Friend Hub test 🛎️",
        body="If you can read this, push notifications are working.",
        url="/home",
        data={"notif_type": "test"},
        # Diagnostics should arrive immediately or visibly fail.
        urgency="high",
        ttl=300,
    )
    return {"status": "sent", "subscription_count": len(subs)}


@router.get("/push/diagnostics")
async def get_push_diagnostics(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Server-side half of the push diagnostics view.

    The frontend combines this with client-side state (permission,
    SW registration, local subscription endpoint) to show which device
    rows are live, stale, or orphaned.
    """
    from urllib.parse import urlparse

    from app.domains.notifications.push_repository import PushSubscriptionRepository

    user = await _current_user_or_401(authorization, db, session_cookie)
    settings = get_settings()
    subs = await PushSubscriptionRepository(db).list_for_user(user.id)
    now = datetime.utcnow()
    return {
        "configured": bool(settings.vapid_public_key and settings.vapid_private_key),
        "subscription_count": len(subs),
        "subscriptions": [
            {
                "id": s.id,
                "endpoint": s.endpoint,
                "endpoint_host": urlparse(s.endpoint).netloc,
                "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "age_days": (now - s.created_at).days if s.created_at else None,
                "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
                "last_failure_at": s.last_failure_at.isoformat() if s.last_failure_at else None,
            }
            for s in subs
        ],
    }


@router.get("/notifications/preferences")
async def get_notification_preferences(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Get the current user's notification preferences."""
    from app.domains.notifications.preferences_repository import NotificationPreferencesRepository

    user = await _current_user_or_401(authorization, db, session_cookie)
    repo = NotificationPreferencesRepository(db)
    prefs = await repo.get_or_create(user.id)
    return {"preferences": repo.preference_payload(prefs)}


@router.put("/notifications/preferences")
async def update_notification_preferences(
    request: NotificationPreferencesUpdate,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Update the current user's notification preferences.

    Only the fields included in the request body will be changed.
    Unset fields keep their current value.
    """
    from app.domains.notifications.preferences_repository import NotificationPreferencesRepository

    user = await _current_user_or_401(authorization, db, session_cookie)
    repo = NotificationPreferencesRepository(db)

    # Only pass fields that were explicitly set
    updates = {k: v for k, v in request.model_dump(exclude_none=True).items()}
    prefs = await repo.update(user.id, updates)
    return {"preferences": repo.preference_payload(prefs)}


# ── Room routes ───────────────────────────────────────────────────────────────

@router.get("/rooms")
async def list_rooms(
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Return all rooms the authenticated user is a member of."""
    from app.domains.rooms.service import RoomService

    user = await _current_user_or_401(authorization, db, session_cookie)
    if getattr(user, "user_type", None) == "guest":
        from app.domains.rooms.repository import RoomRepository
        demo = await RoomRepository(db).get_room_by_slug("demo")
        membership = await RoomRepository(db).get_membership(demo.id, user.id) if demo else None
        from app.domains.rooms.service import _room_payload
        return {"rooms": [_room_payload(demo, membership)]} if demo and membership else {"rooms": []}
    service = RoomService(db)
    rooms = await service.get_rooms_for_user(user.id)
    return {"rooms": rooms}


@router.get("/current-room")
async def get_current_room_info(
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Resolve and return the current room for the authenticated user.

    Resolution order:
    1. X-Room-Slug header → verify membership.
    2. No header + user has exactly one room → return that room.
    3. No header + user has multiple rooms → 400 requiring room selection.
    """
    from app.domains.rooms.service import RoomService

    user = await _current_user_or_401(authorization, db, session_cookie)
    service = RoomService(db)
    room, error = await service.resolve_room(slug=x_room_slug, user_id=user.id)
    if error:
        if "not found" in error or "not a member" in error:
            raise HTTPException(status_code=404, detail=error)
        raise HTTPException(status_code=400, detail=error)

    from app.domains.rooms.repository import RoomRepository
    membership = await RoomRepository(db).get_membership(room.id, user.id)
    from app.domains.rooms.service import _room_payload
    return {"room": _room_payload(room, membership)}


class RoomCreateRequest(BaseModel):
    slug: str
    name: str


@router.post("/rooms")
async def create_room(
    request: RoomCreateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Create a new room. Platform owner only."""
    user = await _current_user_or_401(authorization, db, session_cookie)
    if not _is_owner_user(user):
        raise HTTPException(status_code=403, detail="Owner access required")

    slug = request.slug.strip().lower()
    if not slug or not all(c.isalnum() or c == "-" for c in slug):
        raise HTTPException(status_code=400, detail="Slug must contain only letters, numbers, and hyphens")
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    from app.models.room import Room, RoomSettings
    from app.domains.rooms.repository import RoomRepository

    existing = await RoomRepository(db).get_room_by_slug(slug)
    if existing:
        raise HTTPException(status_code=409, detail=f"Room '{slug}' already exists")

    room = Room(slug=slug, name=name, status="active")
    db.add(room)
    await db.flush()
    db.add(RoomSettings(room_id=room.id))
    await db.commit()
    return {"room": {"id": str(room.id), "slug": room.slug, "name": room.name, "status": room.status}}


class RoomInviteCreateRequest(BaseModel):
    max_uses: int = 1
    expires_days: int = 7


@router.post("/rooms/{room_slug}/invites")
async def create_room_invite(
    room_slug: str,
    request: RoomInviteCreateRequest,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Generate a room invite code. Room admin or owner only."""
    import secrets as _secrets
    from datetime import timedelta
    from app.models.room import RoomInvite
    from app.domains.rooms.repository import RoomRepository

    user = await _current_user_or_401(authorization, db, session_cookie)
    repo = RoomRepository(db)
    room = await repo.get_room_by_slug(room_slug)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if not await repo.is_admin(room.id, user.id):
        raise HTTPException(status_code=403, detail="Room admin access required")

    if request.max_uses < 1:
        raise HTTPException(status_code=400, detail="max_uses must be at least 1")
    if not (1 <= request.expires_days <= 90):
        raise HTTPException(status_code=400, detail="expires_days must be between 1 and 90")

    code = _secrets.token_urlsafe(16)
    expires_at = datetime.utcnow() + timedelta(days=request.expires_days)
    invite = RoomInvite(
        room_id=room.id,
        created_by_user_id=user.id,
        code=code,
        max_uses=request.max_uses,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.commit()
    return {
        "invite": {
            "code": code,
            "room_slug": room.slug,
            "room_name": room.name,
            "max_uses": request.max_uses,
            "expires_at": expires_at.isoformat(),
        }
    }


@router.post("/join/{invite_code}")
async def join_room_via_invite(
    invite_code: str,
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    """Join a room using an invite code."""
    from app.models.room import RoomInvite, RoomMembership, RoomMemberRole
    from app.domains.rooms.repository import RoomRepository

    user = await _current_user_or_401(authorization, db, session_cookie)

    result = await db.execute(
        select(RoomInvite).where(RoomInvite.code == invite_code)
    )
    invite = result.scalar_one_or_none()

    if not invite:
        raise HTTPException(status_code=404, detail="Invite code not found")
    if invite.expires_at and invite.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="Invite code has expired")
    if invite.revoked_at:
        raise HTTPException(status_code=410, detail="Invite code has been revoked")
    if invite.use_count >= invite.max_uses:
        raise HTTPException(status_code=410, detail="Invite code has reached its maximum uses")

    repo = RoomRepository(db)
    room = await repo.get_room_by_id(invite.room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found or inactive")

    already_member = await repo.is_member(room.id, user.id)
    if not already_member:
        db.add(RoomMembership(
            room_id=room.id,
            user_id=user.id,
            role=RoomMemberRole.member.value,
        ))
        invite.use_count += 1
        await db.commit()

    from app.domains.rooms.service import _room_payload
    membership = await repo.get_membership(room.id, user.id)
    return {
        "status": "already_member" if already_member else "joined",
        "room": _room_payload(room, membership),
    }


# ── Videos ───────────────────────────────────────────────────────────────────

def _video_payload(video) -> dict:
    return {
        "id": video.id,
        "url": f"/uploads/videos/{video.filename}",
        "thumbnail_url": f"/uploads/videos/{video.thumbnail_filename}" if video.thumbnail_filename else None,
        "filename": video.filename,
        "original_filename": video.original_filename,
        "content_type": video.content_type,
        "size_bytes": video.size_bytes,
        "duration_seconds": video.duration_seconds,
        "width": video.width,
        "height": video.height,
        "caption": video.caption,
        "tags": video.tags or [],
        "source_type": video.source_type or "manual_upload",
        "taken_at": video.taken_at.isoformat() if video.taken_at else None,
        "created_at": video.created_at.isoformat() if video.created_at else None,
        "message_id": video.message_id,
    }


@router.get("/videos")
async def get_videos(
    limit: int = 30,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    from app.models.video import Video
    room_id = await _request_room_id(db, authorization=authorization, session_cookie=session_cookie, x_room_slug=x_room_slug)
    result = await db.execute(
        select(Video)
        .where(Video.room_id == room_id, Video.deleted_at.is_(None))
        .order_by(desc(Video.created_at))
        .limit(limit)
    )
    videos = result.scalars().all()
    return {"videos": [_video_payload(v) for v in videos], "total": len(videos)}


class VideoUploadRequest(BaseModel):
    filename: str
    content_type: str
    data_url: str
    caption: str | None = None
    tags: list[str] = []


@router.post("/videos")
async def upload_video(
    request: VideoUploadRequest,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    import base64, binascii
    from app.models.video import Video
    from app.domains.videos.service import (
        ACCEPTED_VIDEO_TYPES, process_video,
        get_video_upload_path,
    )

    user = await _current_user_or_401(authorization, db, session_cookie)
    _ensure_not_demo_guest(user)
    room_id = await _request_room_id(db, authorization=authorization, session_cookie=session_cookie, x_room_slug=x_room_slug)

    ct = (request.content_type or "").lower()
    if not any(ct.startswith(t) for t in ACCEPTED_VIDEO_TYPES):
        raise HTTPException(status_code=400, detail="Only video files are supported")

    try:
        _, separator, encoded = request.data_url.partition(",")
        if not separator:
            raise ValueError("missing separator")
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="Invalid video data") from exc

    suffix = "." + request.filename.rsplit(".", 1)[-1].lower() if "." in request.filename else ".mp4"
    processed = process_video(content, original_suffix=suffix)

    upload_dir = get_video_upload_path()
    vid_id = uuid.uuid4().hex
    filename = f"{vid_id}.mp4"
    thumb_filename = f"{vid_id}_thumb.jpg" if processed.thumbnail_bytes else None

    (upload_dir / filename).write_bytes(processed.video_bytes)
    if thumb_filename and processed.thumbnail_bytes:
        (upload_dir / thumb_filename).write_bytes(processed.thumbnail_bytes)

    video = Video(
        filename=filename,
        thumbnail_filename=thumb_filename,
        original_filename=request.filename,
        content_type="video/mp4",
        size_bytes=processed.size_bytes,
        duration_seconds=processed.duration_seconds,
        width=processed.width,
        height=processed.height,
        caption=request.caption,
        tags=request.tags or [],
        storage_path=f"/uploads/videos/{filename}",
        uploaded_by_session_id=user.session_id,
        room_id=room_id,
    )
    db.add(video)
    await db.commit()
    return {"video": _video_payload(video)}


@router.delete("/videos/{video_id}")
async def delete_video(
    video_id: int,
    authorization: str | None = Header(default=None),
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    from app.models.video import Video
    user = await _current_user_or_401(authorization, db, session_cookie)
    room_id = await _request_room_id(db, authorization=authorization, session_cookie=session_cookie, x_room_slug=x_room_slug)
    video = await db.get(Video, video_id)
    if not video or video.room_id != room_id or video.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Video not found")
    if not _can_manage_creator_owned_item(user, video.uploaded_by_session_id):
        raise HTTPException(status_code=403, detail="Not allowed to delete this video")
    video.deleted_at = datetime.utcnow()
    video.deleted_by_user_id = user.id
    await db.commit()
    return {"status": "deleted"}


# ── Audio ────────────────────────────────────────────────────────────────────

def _audio_payload(audio) -> dict:
    return {
        "id": audio.id,
        "url": f"/uploads/audio/{audio.filename}",
        "filename": audio.filename,
        "original_filename": audio.original_filename,
        "content_type": audio.content_type,
        "size_bytes": audio.size_bytes,
        "duration_seconds": audio.duration_seconds,
        "source_type": audio.source_type,
        "message_id": audio.message_id,
        "taken_at": audio.taken_at.isoformat() if audio.taken_at else None,
        "created_at": audio.created_at.isoformat() if audio.created_at else None,
    }


@router.get("/audio")
async def get_audio_files(
    limit: int = 30,
    x_room_slug: str | None = Header(default=None, alias="X-Room-Slug"),
    authorization: str | None = Header(default=None),
    session_cookie: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: AsyncSession = Depends(get_db_session),
):
    from app.models.video import AudioFile

    room_id = await _request_room_id(
        db,
        authorization=authorization,
        session_cookie=session_cookie,
        x_room_slug=x_room_slug,
    )
    result = await db.execute(
        select(AudioFile)
        .where(AudioFile.room_id == room_id)
        .order_by(desc(AudioFile.taken_at).nulls_last(), desc(AudioFile.created_at))
        .limit(limit)
    )
    audio_files = result.scalars().all()
    return {"audio": [_audio_payload(a) for a in audio_files], "total": len(audio_files)}
