"""
Member profile (Chat Council Phase 1).

Holds the profile metadata service and the governance-policy enums that future
phases will lean on. Voting is not implemented yet — for now the policy enum
exists so the permission check has one clear branch to extend.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import MemberRole
from app.models.message import User


class NicknameChangePolicy(str, enum.Enum):
    admin_only = "admin_only"
    self_edit = "self_edit"
    vote_required = "vote_required"
    free_for_all = "free_for_all"


# Phase 1 default — admins or the user themselves can edit. Phase 2 will
# replace this with a per-group setting and the vote_required branch.
DEFAULT_NICKNAME_POLICY = NicknameChangePolicy.self_edit


# Cosmetic role labels (Jester, Vibes Officer, …) are user-supplied strings.
# Access role (owner/admin/member) is unrelated and only changes via the
# /members/{id}/role endpoint.
DISPLAY_ROLE_MAX = 64
BIO_MAX = 500
AVATAR_EMOJI_MAX = 8
NICKNAME_MIN = 2
NICKNAME_MAX = 64


@dataclass
class ProfileUpdate:
    nickname: Optional[str] = None
    display_role: Optional[str] = None
    bio: Optional[str] = None
    avatar_emoji: Optional[str] = None

    def is_empty(self) -> bool:
        return all(v is None for v in (self.nickname, self.display_role, self.bio, self.avatar_emoji))


class ProfileError(Exception):
    """Raised when a profile update is invalid or not allowed."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def can_edit_profile(
    *,
    requester_session_id: str,
    requester_role: MemberRole,
    target_session_id: str,
    policy: NicknameChangePolicy = DEFAULT_NICKNAME_POLICY,
    field: str = "nickname",
) -> bool:
    """
    Permission gate for profile edits. Phase 1 only enforces nickname policy;
    other fields (display_role, bio, avatar_emoji) follow the same default rule
    so the surface stays consistent. Voting is not honoured yet — vote_required
    falls back to admin_only until Phase 2.
    """
    if requester_role in {MemberRole.owner, MemberRole.admin}:
        return True

    is_self = requester_session_id == target_session_id

    if field == "nickname":
        if policy == NicknameChangePolicy.admin_only:
            return False
        if policy == NicknameChangePolicy.self_edit:
            return is_self
        if policy == NicknameChangePolicy.vote_required:
            return False  # Phase 2 will plug voting in here.
        if policy == NicknameChangePolicy.free_for_all:
            return True

    # display_role / bio / avatar_emoji default to self-edit in Phase 1.
    return is_self


class ProfileRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_session_id(self, session_id: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.session_id == session_id)
        )
        return result.scalar_one_or_none()

    async def update_profile(self, session_id: str, values: dict) -> Optional[User]:
        if not values:
            return await self.get_by_session_id(session_id)
        await self.db.execute(
            update(User).where(User.session_id == session_id).values(**values)
        )
        await self.db.commit()
        return await self.get_by_session_id(session_id)


def serialize_profile(user: User) -> dict:
    role_value = user.role.value if hasattr(user.role, "value") else (user.role or "member")
    return {
        "id": str(user.id) if user.id else None,
        "session_id": str(user.session_id),
        "username": user.username,
        "nickname": user.nickname,
        "role": role_value or "member",
        "display_role": user.display_role,
        "bio": user.bio,
        "avatar_url": user.avatar_url,
        "avatar_emoji": user.avatar_emoji or ("🤖" if user.is_bot else None),
        "is_bot": bool(user.is_bot),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }


def _clean_optional(value: Optional[str], *, max_length: int, allow_blank: bool = True) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return "" if allow_blank else None
    if len(cleaned) > max_length:
        raise ProfileError(f"Value exceeds {max_length} characters", status_code=400)
    return cleaned


def validate_nickname(nickname: str) -> str:
    cleaned = (nickname or "").strip()
    if not cleaned:
        raise ProfileError("Nickname is required")
    if len(cleaned) < NICKNAME_MIN:
        raise ProfileError(f"Nickname must be at least {NICKNAME_MIN} characters")
    if len(cleaned) > NICKNAME_MAX:
        raise ProfileError(f"Nickname must be {NICKNAME_MAX} characters or less")
    if any(ch in cleaned for ch in "\r\n\t"):
        raise ProfileError("Nickname cannot contain line breaks or tabs")
    return cleaned


def validate_display_role(display_role: str) -> str:
    cleaned = _clean_optional(display_role, max_length=DISPLAY_ROLE_MAX, allow_blank=False)
    if not cleaned:
        raise ProfileError("Display role is required")
    if any(ch in cleaned for ch in "\r\n\t"):
        raise ProfileError("Display role cannot contain line breaks or tabs")
    return cleaned


def normalize_update(update_in: ProfileUpdate) -> dict:
    """Validate and normalise a ProfileUpdate into a SQL values dict."""
    values: dict = {}
    if update_in.nickname is not None:
        values["nickname"] = validate_nickname(update_in.nickname)
    if update_in.display_role is not None:
        cleaned = _clean_optional(update_in.display_role, max_length=DISPLAY_ROLE_MAX)
        values["display_role"] = cleaned or None
    if update_in.bio is not None:
        cleaned = _clean_optional(update_in.bio, max_length=BIO_MAX)
        values["bio"] = cleaned or None
    if update_in.avatar_emoji is not None:
        cleaned = _clean_optional(update_in.avatar_emoji, max_length=AVATAR_EMOJI_MAX)
        values["avatar_emoji"] = cleaned or None
    return values
