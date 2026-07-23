"""
User repository for data access operations.
Implements the repository pattern to separate data access from business logic.
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.models.member import GroupMember, MemberRole
from app.models.message import User, UserRole  # Update import path as needed


class UserRepository:
    """Repository for user data access operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_session_id(self, session_id: str) -> Optional[User]:
        """Get user by session ID."""
        result = await self.db.execute(
            select(User).where(User.session_id == session_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_nickname(self, nickname: str) -> Optional[User]:
        """Get user by nickname."""
        result = await self.db.execute(
            select(User).where(User.nickname == nickname)
        )
        return result.scalar_one_or_none()
    
    async def create(self, session_id: str, nickname: str) -> User:
        """Create a new user."""
        result = await self.db.execute(select(func.count(User.session_id)))
        is_first_user = (result.scalar_one() or 0) == 0
        role = UserRole.owner if is_first_user else UserRole.member

        user = User(
            session_id=session_id,
            nickname=nickname,
            role=role,
            joined_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            last_seen_at=datetime.utcnow(),
        )
        
        self.db.add(user)
        await self.db.flush()
        self.db.add(GroupMember(user_session_id=user.session_id, role=MemberRole(role.value)))
        await self.db.commit()
        await self.db.refresh(user)
        return user
    
    async def update_nickname(self, session_id: str, nickname: str) -> Optional[User]:
        """Update user nickname."""
        try:
            await self.db.execute(
                update(User)
                .where(User.session_id == session_id)
                .values(nickname=nickname, last_seen=datetime.utcnow())
            )
            await self.db.commit()
            return await self.get_by_session_id(session_id)
        except IntegrityError:
            await self.db.rollback()
            return None
    
    async def update_last_seen(self, session_id: str) -> None:
        """Update user's last seen timestamp."""
        await self.db.execute(
            update(User)
            .where(User.session_id == session_id)
            .values(last_seen=datetime.utcnow())
        )
        await self.db.commit()
    
    async def get_active_users(self, since: datetime) -> List[User]:
        """Get users active since a certain time."""
        result = await self.db.execute(
            select(User).where(User.last_seen >= since)
        )
        return result.scalars().all()
    
    async def delete_by_session_id(self, session_id: str) -> bool:
        """Delete user by session ID."""
        user = await self.get_by_session_id(session_id)
        if user:
            await self.db.delete(user)
            await self.db.commit()
            return True
        return False
    
    async def nickname_exists(self, nickname: str, exclude_session_id: str = None) -> bool:
        """Check if nickname already exists (optionally excluding a session)."""
        query = select(User).where(User.nickname == nickname)
        if exclude_session_id:
            query = query.where(User.session_id != exclude_session_id)
        
        result = await self.db.execute(query)
        return result.scalar_one_or_none() is not None
    
    async def get_all_members_with_stats(self) -> List[dict]:
        """Get all users with message count and join date."""
        from sqlalchemy import func
        from app.models.message import Message
        
        result = await self.db.execute(
            select(
                User.session_id,
                User.nickname,
                func.count(Message.id).label('message_count'),
                User.joined_at
            )
            .outerjoin(Message, User.session_id == Message.user_session_id)
            .group_by(User.session_id, User.nickname, User.joined_at)
            .order_by(User.joined_at.desc())
        )
        
        rows = result.fetchall()
        return [
            {
                'session_id': str(row.session_id),
                'nickname': row.nickname,
                'message_count': row.message_count or 0,
                'joined_at': row.joined_at.isoformat() if row.joined_at else None,
            }
            for row in rows
        ]
