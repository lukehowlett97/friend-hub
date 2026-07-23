"""
User service for business logic operations.
Contains user-related business rules and validation logic.
"""
import re
from typing import Optional, Tuple, List
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession

from .repository import UserRepository
from app.models.message import User  # Update import path as needed


class UserService:
    """Service for user business logic."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repository = UserRepository(db)
    
    async def create_or_update_user(self, session_id: str, nickname: str) -> Tuple[Optional[User], Optional[str]]:
        """
        Create or update a user with validation.
        Returns (user, error_message).
        """
        # Validate nickname
        validation_error = self._validate_nickname(nickname)
        if validation_error:
            return None, validation_error
        
        # Check if nickname is already taken by another user
        if await self.repository.nickname_exists(nickname, exclude_session_id=session_id):
            return None, "Nickname is already taken"
        
        # Check if user already exists
        existing_user = await self.repository.get_by_session_id(session_id)
        
        if existing_user:
            # Update existing user
            user = await self.repository.update_nickname(session_id, nickname)
            if user:
                return user, None
            else:
                return None, "Failed to update nickname"
        else:
            # Create new user
            try:
                user = await self.repository.create(session_id, nickname)
                return user, None
            except Exception:
                await self.db.rollback()
                return None, "Failed to create user"
    
    async def get_user(self, session_id: str) -> Optional[User]:
        """Get user by session ID."""
        return await self.repository.get_by_session_id(session_id)
    
    async def update_last_seen(self, session_id: str) -> None:
        """Update user's last seen timestamp."""
        await self.repository.update_last_seen(session_id)
    
    async def get_active_users(self, minutes: int = 30) -> List[User]:
        """Get users active within the specified minutes."""
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
        return await self.repository.get_active_users(cutoff_time)
    
    async def get_all_members_with_stats(self) -> List[dict]:
        """Get all members with their stats (message count, joined date)."""
        return await self.repository.get_all_members_with_stats()
    
    async def is_nickname_available(self, nickname: str, session_id: str = None) -> bool:
        """Check if nickname is available."""
        validation_error = self._validate_nickname(nickname)
        if validation_error:
            return False
        
        return not await self.repository.nickname_exists(nickname, exclude_session_id=session_id)
    
    def _validate_nickname(self, nickname: str) -> Optional[str]:
        """
        Validate nickname according to business rules.
        Returns error message if invalid, None if valid.
        """
        if not nickname or not nickname.strip():
            return "Nickname is required"
        
        nickname = nickname.strip()
        
        if len(nickname) < 2:
            return "Nickname must be at least 2 characters long"
        
        if len(nickname) > 20:
            return "Nickname must be less than 20 characters long"
        
        # Allow only letters, numbers, hyphens, and underscores (matching original)
        if not re.match(r'^[a-zA-Z0-9_-]+$', nickname):

            return "Nickname can only contain letters, numbers, hyphens, and underscores"
        
        return None
