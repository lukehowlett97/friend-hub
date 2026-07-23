import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.auth.repository import AuthRepository
from app.domains.auth.tokens import generate_invite_code, generate_session_token, hash_secret, hash_session_token, verify_secret
from app.models.message import User, UserRole
from app.models.room import Room, RoomMembership, RoomMemberRole
from app.models.user_session import UserSession
import random


class AuthService:
    SESSION_DAYS = 90
    INVITE_DAYS = 14
    MAX_FAILED_LOGINS = 5
    LOCK_MINUTES = 10
    GENERIC_LOGIN_ERROR = "Login failed. Check your details and try again."
    PLATFORM_OWNER_USERNAME = "techlett"
    DEMO_SESSION_HOURS = 2
    DEMO_ADJECTIVES = ("Amber", "Blue", "Bright", "Calm", "Clever", "Coral", "Cosmic", "Daring", "Golden", "Happy", "Indigo", "Jolly", "Lucky", "Misty", "Neon", "Quiet", "Silver", "Sunny")
    DEMO_ANIMALS = ("Fox", "Otter", "Panda", "Raven", "Robin", "Seal", "Sparrow", "Tiger", "Wolf", "Wren")

    def __init__(self, db: AsyncSession):
        self.repository = AuthRepository(db)
        self.settings = get_settings()

    async def register(
        self,
        *,
        username: str,
        nickname: str,
        invite_code: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[Optional[User], Optional[str], Optional[str]]:
        username = username.strip().lower()
        nickname = nickname.strip()

        error = self._validate_invite_code(invite_code)
        if error:
            return None, None, error

        error = self._validate_username(username)
        if error:
            return None, None, error

        error = self._validate_nickname(nickname)
        if error:
            return None, None, error

        if await self.repository.get_user_by_username(username):
            return None, None, "Username is already taken"

        raw_token = generate_session_token()
        user, _ = await self.repository.create_user_with_session(
            username=username,
            nickname=nickname,
            token_hash=hash_session_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(days=self.SESSION_DAYS),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return user, raw_token, None

    async def create_demo_guest(
        self,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[Optional[User], Optional[str], Optional[str]]:
        """Create a short-lived, room-limited visitor session for the demo."""
        room = (await self.repository.db.execute(
            select(Room).where(Room.slug == "demo", Room.status == "active")
        )).scalar_one_or_none()
        if not room:
            return None, None, "Demo room is not configured"

        now = datetime.utcnow()
        nickname = f"{random.choice(self.DEMO_ADJECTIVES)} {random.choice(self.DEMO_ANIMALS)}"
        user = User(
            username=None,
            nickname=nickname,
            display_name=nickname,
            role=UserRole.member,
            user_type="guest",
            is_test_user=True,
            joined_at=now,
            last_seen=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        self.repository.db.add(user)
        await self.repository.db.flush()

        raw_token = generate_session_token()
        session = UserSession(
            user_id=user.id,
            token_hash=hash_session_token(raw_token),
            expires_at=now + timedelta(hours=self.DEMO_SESSION_HOURS),
            last_used_at=now,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.repository.db.add(session)
        self.repository.db.add(RoomMembership(
            room_id=room.id,
            user_id=user.id,
            role=RoomMemberRole.member.value,
        ))
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, raw_token, None

    async def authenticate_token(self, token: str | None) -> tuple[Optional[User], Optional[UserSession]]:
        if not token:
            return None, None

        session = await self.repository.get_session_by_token_hash(hash_session_token(token))
        if not session or self._is_expired(session.expires_at):
            return None, None

        user = await self.repository.get_user_by_id(session.user_id)
        if not user:
            return None, None

        await self.repository.touch_session_and_user(session, user)
        return user, session

    async def create_admin_user(
        self,
        *,
        username: str,
        display_name: str,
        role: str = "member",
    ) -> tuple[Optional[User], Optional[str], Optional[str]]:
        username = username.strip().lower()
        display_name = display_name.strip()
        error = self._validate_username(username) or self._validate_display_name(display_name)
        if error:
            return None, None, error
        role_value = self._role_or_error(role)
        if role_value is None:
            return None, None, "Role must be owner, admin, or member"
        if not self._can_have_owner_role(username, role_value):
            return None, None, "Only techlett can be the platform owner"
        if await self.repository.get_user_by_username(username):
            return None, None, "Username is already taken"

        invite_code = generate_invite_code()
        user = await self.repository.create_user(
            username=username,
            display_name=display_name,
            role=role_value,
            invite_code_hash=hash_secret(invite_code),
            invite_code_expires_at=datetime.utcnow() + timedelta(days=self.INVITE_DAYS),
        )
        return user, invite_code, None

    async def peek_invite(self, invite_code: str) -> tuple[Optional[dict], Optional[str]]:
        """Resolve an invite code to its target display name without consuming it.

        Returns (invite_payload, error). Used by the /join landing page to greet
        the invitee and surface expired/used codes before they enter a PIN.
        """
        code = (invite_code or "").strip()
        if not code:
            return None, "Invalid or expired invite code"
        users = await self.repository.list_users()
        user = next((u for u in users if u.invite_code_hash and verify_secret(code, u.invite_code_hash)), None)
        if not user or user.invite_code_used_at or not user.invite_code_expires_at or self._is_expired(user.invite_code_expires_at):
            return None, "Invalid or expired invite code"

        room_row = (await self.repository.db.execute(
            select(Room)
            .join(RoomMembership, Room.id == RoomMembership.room_id)
            .where(RoomMembership.user_id == user.id)
            .order_by(Room.name.asc(), Room.created_at.asc())
            .limit(1)
        )).scalar_one_or_none()

        return {
            "display_name": user.display_name or user.nickname or user.username,
            "room": {
                "id": str(room_row.id),
                "slug": room_row.slug,
                "name": room_row.name,
            } if room_row else None,
        }, None

    async def claim_invite(
        self,
        *,
        invite_code: str,
        pin: str,
        pin_confirm: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[Optional[User], Optional[str], Optional[str]]:
        if pin != pin_confirm:
            return None, None, "PIN confirmation does not match"
        error = self._validate_pin(pin)
        if error:
            return None, None, error

        users = await self.repository.list_users()
        now = datetime.utcnow()
        user = next((u for u in users if u.invite_code_hash and verify_secret(invite_code.strip(), u.invite_code_hash)), None)
        if not user or user.invite_code_used_at or not user.invite_code_expires_at or self._is_expired(user.invite_code_expires_at):
            return None, None, "Invalid or expired invite code"

        user.pin_hash = hash_secret(pin)
        user.invite_code_used_at = now
        user.invite_code_hash = None
        user.is_active = True
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        user.last_seen_at = now
        user.last_seen = now
        user.updated_at = now
        token = await self._create_session_for_user(user, user_agent=user_agent, ip_address=ip_address)
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, token, None

    async def pin_login(
        self,
        *,
        username: str,
        pin: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[Optional[User], Optional[str], Optional[str]]:
        username = username.strip().lower()
        now = datetime.utcnow()
        user = await self.repository.get_user_by_username(username) if username else None
        if not user or not user.is_active:
            return None, None, self.GENERIC_LOGIN_ERROR
        if user.locked_until and not self._is_expired(user.locked_until):
            return None, None, self.GENERIC_LOGIN_ERROR
        if not verify_secret(pin, user.pin_hash):
            user.failed_login_count = (user.failed_login_count or 0) + 1
            if user.failed_login_count >= self.MAX_FAILED_LOGINS:
                user.locked_until = now + timedelta(minutes=self.LOCK_MINUTES)
            user.updated_at = now
            await self.repository.db.commit()
            return None, None, self.GENERIC_LOGIN_ERROR

        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        user.last_seen_at = now
        user.last_seen = now
        user.updated_at = now
        token = await self._create_session_for_user(user, user_agent=user_agent, ip_address=ip_address)
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, token, None

    async def reset_pin(self, user_id) -> tuple[Optional[User], Optional[str], Optional[str]]:
        user = await self.repository.get_user_by_public_id(user_id)
        if not user:
            return None, None, "User not found"
        invite_code = generate_invite_code()
        user.pin_hash = None
        user.invite_code_hash = hash_secret(invite_code)
        user.invite_code_used_at = None
        user.invite_code_expires_at = datetime.utcnow() + timedelta(days=self.INVITE_DAYS)
        user.failed_login_count = 0
        user.locked_until = None
        user.updated_at = datetime.utcnow()
        await self.repository.revoke_sessions_for_user(user)
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, invite_code, None

    async def deactivate_user(self, user_id) -> tuple[Optional[User], Optional[str]]:
        user = await self.repository.get_user_by_public_id(user_id)
        if not user:
            return None, "User not found"
        if self._is_owner(user) and await self.repository.count_active_owners() <= 1:
            return None, "Cannot deactivate the final active owner"
        user.is_active = False
        user.status = "deactivated"
        user.deactivated_at = user.deactivated_at or datetime.utcnow()
        user.updated_at = datetime.utcnow()
        await self.repository.revoke_sessions_for_user(user)
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, None

    async def reactivate_user(self, user_id) -> tuple[Optional[User], Optional[str]]:
        user = await self.repository.get_user_by_public_id(user_id)
        if not user:
            return None, "User not found"
        user.is_active = True
        user.status = "active"
        user.deactivated_at = None
        user.updated_at = datetime.utcnow()
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, None

    async def update_role(self, user_id, role: str) -> tuple[Optional[User], Optional[str]]:
        user = await self.repository.get_user_by_public_id(user_id)
        role_value = self._role_or_error(role)
        if not user:
            return None, "User not found"
        if role_value is None:
            return None, "Role must be owner, admin, or member"
        if not self._can_have_owner_role(user.username or "", role_value):
            return None, "Only techlett can be the platform owner"
        if self._is_owner(user) and role_value != UserRole.owner and user.is_active and await self.repository.count_active_owners() <= 1:
            return None, "Cannot demote the final active owner"
        user.role = role_value
        user.updated_at = datetime.utcnow()
        await self.repository.db.commit()
        await self.repository.db.refresh(user)
        return user, None

    async def logout(self, token: str | None) -> bool:
        user, session = await self.authenticate_token(token)
        if not user or not session:
            return False
        await self.repository.revoke_session(session)
        return True

    async def update_nickname(self, token: str | None, nickname: str) -> tuple[Optional[User], Optional[str]]:
        user, _ = await self.authenticate_token(token)
        if not user:
            return None, "Authentication required"

        nickname = nickname.strip()
        error = self._validate_nickname(nickname)
        if error:
            return None, error

        return await self.repository.update_nickname(user, nickname), None

    async def _create_session_for_user(self, user: User, *, user_agent: str | None, ip_address: str | None) -> str:
        raw_token = generate_session_token()
        await self.repository.create_session(
            user,
            token_hash=hash_session_token(raw_token),
            expires_at=datetime.utcnow() + timedelta(days=self.SESSION_DAYS),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return raw_token

    def _validate_invite_code(self, invite_code: str) -> Optional[str]:
        if not invite_code or invite_code != self.settings.invite_code:
            return "Invalid invite code"
        return None

    @staticmethod
    def _validate_username(username: str) -> Optional[str]:
        if not username:
            return "Username is required"
        if len(username) < 3:
            return "Username must be at least 3 characters long"
        if len(username) > 32:
            return "Username must be 32 characters or less"
        if not re.match(r"^[a-z0-9_][a-z0-9_-]*$", username):
            return "Username can only contain lowercase letters, numbers, underscores, and hyphens"
        return None

    @staticmethod
    def _validate_nickname(nickname: str) -> Optional[str]:
        if not nickname:
            return "Nickname is required"
        if len(nickname) < 2:
            return "Nickname must be at least 2 characters long"
        if len(nickname) > 64:
            return "Nickname must be 64 characters or less"
        if any(char in nickname for char in "\r\n\t"):
            return "Nickname cannot contain line breaks or tabs"
        return None

    @staticmethod
    def _validate_display_name(display_name: str) -> Optional[str]:
        return AuthService._validate_nickname(display_name).replace("Nickname", "Display name") if AuthService._validate_nickname(display_name) else None

    @staticmethod
    def _validate_pin(pin: str) -> Optional[str]:
        if not re.fullmatch(r"\d{6}", pin or ""):
            return "PIN must be exactly 6 digits"
        return None

    @staticmethod
    def _role_or_error(role: str) -> Optional[UserRole]:
        normalized = (role or "member").strip().lower()
        if normalized == "owner":
            return UserRole.owner
        if normalized == "admin":
            return UserRole.admin
        if normalized == "member":
            return UserRole.member
        return None

    @staticmethod
    def _is_admin(user: User) -> bool:
        role = user.role.value if hasattr(user.role, "value") else user.role
        return role in {"owner", "admin"}

    @staticmethod
    def _is_owner(user: User) -> bool:
        role = user.role.value if hasattr(user.role, "value") else user.role
        return role == "owner"

    @classmethod
    def _can_have_owner_role(cls, username: str, role: UserRole) -> bool:
        return role != UserRole.owner or (username or "").strip().lower() == cls.PLATFORM_OWNER_USERNAME

    @staticmethod
    def _is_expired(expires_at: datetime) -> bool:
        if expires_at.tzinfo is None:
            return expires_at <= datetime.utcnow()
        return expires_at <= datetime.now(timezone.utc)


def user_payload(user: User) -> dict:
    role = user.role.value if user.role else "member"
    return {
        "id": str(user.id),
        "session_id": str(user.session_id),
        "username": user.username,
        "nickname": user.nickname,
        "display_name": getattr(user, "display_name", None) or user.nickname,
        "role": role,
        "is_admin": role in {"owner", "admin"},
        "is_owner": role == "owner",
        "avatar_url": getattr(user, "avatar_url", None),
        "is_guest": getattr(user, "user_type", "human") == "guest",
    }


def admin_user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name or user.nickname,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "is_active": bool(user.is_active),
        "user_type": getattr(user, "user_type", "human"),
        "status": getattr(user, "status", "active"),
        "is_test_user": bool(getattr(user, "is_test_user", False)),
        "is_bot": bool(getattr(user, "is_bot", False)),
        "hidden_from_member_list": bool(getattr(user, "hidden_from_member_list", False)),
        "deactivated_at": getattr(user, "deactivated_at", None),
        "has_pin": bool(user.pin_hash),
        "invite_pending": bool(user.invite_code_hash and not user.invite_code_used_at),
        "invite_code_used_at": user.invite_code_used_at,
        "invite_code_expires_at": user.invite_code_expires_at,
        "locked_until": user.locked_until,
        "failed_login_count": user.failed_login_count or 0,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }
