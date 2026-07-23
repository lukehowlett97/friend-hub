from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.message import User
from datetime import datetime, timedelta

class UserOperations:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
    
    async def get_user_by_session_id(self, session_id: str) -> Optional[User]:
        """Get user by session ID."""
        result = await self.db.execute(
            select(User).where(User.session_id == session_id)
        )
        return result.scalar_one_or_none()
    
    async def get_all_active_users(self, minutes_threshold: int = 30) -> List[User]:
        """Get all users who were active within the last N minutes."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_threshold)
        result = await self.db.execute(
            select(User).where(User.last_seen >= cutoff_time)
        )
        return result.scalars().all()
    
    async def get_user_by_nickname(self, nickname: str) -> Optional[User]:
        """Get user by nickname (case-insensitive)."""
        result = await self.db.execute(
            select(User).where(func.lower(User.nickname) == func.lower(nickname))
        )
        return result.scalar_one_or_none()
    
    async def update_last_seen(self, session_id: str) -> bool:
        """Update user's last_seen timestamp."""
        user = await self.get_user_by_session_id(session_id)
        if user:
            user.last_seen = datetime.utcnow()
            await self.db.commit()
            return True
        return False
    
    async def delete_user(self, session_id: str) -> bool:
        """Delete user and all their messages."""
        user = await self.get_user_by_session_id(session_id)
        if user:
            await self.db.delete(user)
            await self.db.commit()
            return True
        return False
