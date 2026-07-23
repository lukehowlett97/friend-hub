from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import GroupMember, MemberRole
from app.models.message import User, UserRole
from app.models.user_session import UserSession


class AuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_username(self, username: str) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(func.lower(User.username) == username.lower())
        )
        return result.scalar_one_or_none()

    async def count_active_users(self) -> int:
        result = await self.db.execute(
            select(func.count(User.session_id)).where(User.is_active.is_(True))
        )
        return result.scalar_one() or 0

    async def count_active_admins(self) -> int:
        result = await self.db.execute(
            select(func.count(User.session_id))
            .where(User.is_active.is_(True))
            .where(User.role.in_([UserRole.owner, UserRole.admin]))
        )
        return result.scalar_one() or 0

    async def count_active_owners(self) -> int:
        result = await self.db.execute(
            select(func.count(User.session_id))
            .where(User.is_active.is_(True))
            .where(User.role == UserRole.owner)
        )
        return result.scalar_one() or 0

    async def list_users(self) -> list[User]:
        result = await self.db.execute(select(User).order_by(User.created_at.desc()))
        return list(result.scalars().all())

    async def get_user_by_public_id(self, user_id) -> Optional[User]:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def create_user_with_session(
        self,
        *,
        username: str,
        nickname: str,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[User, UserSession]:
        role = UserRole.owner if await self.count_active_users() == 0 and username.lower() == "techlett" else UserRole.member
        now = datetime.utcnow()
        user = User(
            username=username,
            nickname=nickname,
            role=role,
            joined_at=now,
            last_seen=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )

        self.db.add(user)
        await self.db.flush()

        self.db.add(
            GroupMember(
                user_session_id=user.session_id,
                role=MemberRole(role.value),
                created_at=now,
            )
        )
        session = UserSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            last_used_at=now,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(user)
        await self.db.refresh(session)
        return user, session

    async def get_session_by_token_hash(self, token_hash: str) -> Optional[UserSession]:
        result = await self.db.execute(
            select(UserSession)
            .where(UserSession.token_hash == token_hash)
            .where(UserSession.revoked_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id) -> Optional[User]:
        result = await self.db.execute(
            select(User).where(User.id == user_id).where(User.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def create_user(
        self,
        *,
        username: str,
        display_name: str,
        role: UserRole,
        invite_code_hash: str,
        invite_code_expires_at: datetime,
    ) -> User:
        now = datetime.utcnow()
        user = User(
            username=username,
            nickname=display_name,
            display_name=display_name,
            role=role,
            invite_code_hash=invite_code_hash,
            invite_code_expires_at=invite_code_expires_at,
            is_active=True,
            failed_login_count=0,
            joined_at=now,
            last_seen=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        self.db.add(user)
        await self.db.flush()
        self.db.add(GroupMember(user_session_id=user.session_id, role=MemberRole(role.value), created_at=now))
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def create_session(
        self,
        user: User,
        *,
        token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> UserSession:
        now = datetime.utcnow()
        session = UserSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            last_used_at=now,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def revoke_sessions_for_user(self, user: User) -> None:
        await self.db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id)
            .where(UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.utcnow())
        )

    async def touch_session_and_user(self, session: UserSession, user: User) -> None:
        now = datetime.utcnow()
        await self.db.execute(
            update(UserSession)
            .where(UserSession.id == session.id)
            .values(last_used_at=now)
        )
        await self.db.execute(
            update(User)
            .where(User.id == user.id)
            .values(last_seen_at=now, last_seen=now)
        )
        await self.db.commit()

    async def revoke_session(self, session: UserSession) -> None:
        await self.db.execute(
            update(UserSession)
            .where(UserSession.id == session.id)
            .values(revoked_at=datetime.utcnow())
        )
        await self.db.commit()

    async def update_nickname(self, user: User, nickname: str) -> User:
        now = datetime.utcnow()
        await self.db.execute(
            update(User)
            .where(User.id == user.id)
            .values(nickname=nickname, updated_at=now, last_seen_at=now, last_seen=now)
        )
        await self.db.commit()
        refreshed = await self.get_user_by_id(user.id)
        return refreshed or user
