"""
ChatService — lightweight orchestrator that delegates to domain services.
"""
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.users.service import UserService
from app.domains.messages.service import MessageService
from app.models.message import User, Message


class ChatService:
    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.user_service    = UserService(db_session)
        self.message_service = MessageService(db_session)

    # ── User ────────────────────────────────────────────────────────────────

    async def create_or_update_user(
        self, session_id: str, nickname: str
    ) -> Tuple[Optional[User], Optional[str]]:
        return await self.user_service.create_or_update_user(session_id, nickname)

    async def get_user_by_session(self, session_id: str) -> Optional[User]:
        return await self.user_service.get_user(session_id)

    async def update_user_last_seen(self, session_id: str) -> None:
        await self.user_service.update_last_seen(session_id)

    # ── Messages ─────────────────────────────────────────────────────────────

    async def save_message(
        self,
        session_id: str,
        content: str,
        reply_to_id: Optional[int] = None,
        user_id=None,
        room_id=None,
    ) -> Tuple[Message, str, Optional[dict]]:
        """Returns (message, nickname, reply_to_dict)."""
        return await self.message_service.save_message(
            session_id, content, reply_to_id=reply_to_id, user_id=user_id, room_id=room_id,
        )

    async def get_recent_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        room_id=None,
    ) -> List[dict]:
        return await self.message_service.get_recent_messages(
            limit=limit,
            offset=offset,
            start_at=start_at,
            end_at=end_at,
            room_id=room_id,
        )

    # ── Reactions ─────────────────────────────────────────────────────────────

    async def delete_message(self, message_id: int, requesting_session_id: str) -> bool:
        return await self.message_service.delete_message(message_id, requesting_session_id)

    async def edit_message(
        self, message_id: int, requesting_session_id: str, new_content: str
    ):
        return await self.message_service.edit_message(message_id, requesting_session_id, new_content)

    async def toggle_reaction(
        self, message_id: int, session_id: str, emoji: str, user_id=None
    ) -> List[dict]:
        """Toggle a reaction and return the updated reaction list for the message."""
        return await self.message_service.toggle_reaction(message_id, session_id, emoji, user_id=user_id)

    # ── Nickname validation (legacy) ──────────────────────────────────────────

    def validate_nickname(self, nickname: str) -> Optional[str]:
        return self.user_service._validate_nickname(nickname)

    async def is_nickname_taken(
        self, nickname: str, exclude_session_id: str = None
    ) -> bool:
        return not await self.user_service.is_nickname_available(
            nickname, exclude_session_id
        )
