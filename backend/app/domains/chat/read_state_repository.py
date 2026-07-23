"""
Per-user, per-room chat read-state data access.
"""
import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_read_state import ChatReadState
from app.models.message import Message

logger = logging.getLogger(__name__)


class ChatReadStateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: uuid.UUID, room_id: uuid.UUID) -> Optional[ChatReadState]:
        result = await self.db.execute(
            select(ChatReadState).where(
                ChatReadState.user_id == user_id,
                ChatReadState.room_id == room_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_forward(self, user_id: uuid.UUID, room_id: uuid.UUID, message_id: int) -> ChatReadState:
        """Record the latest message a user has read. Never moves backwards."""
        state = await self.get(user_id, room_id)
        if state is None:
            state = ChatReadState(
                user_id=user_id,
                room_id=room_id,
                last_read_message_id=message_id,
                updated_at=datetime.utcnow(),
            )
            self.db.add(state)
        elif message_id > state.last_read_message_id:
            state.last_read_message_id = message_id
            state.updated_at = datetime.utcnow()
        await self.db.flush()
        return state

    async def count_messages_after(self, room_id: uuid.UUID, message_id: Optional[int]) -> int:
        """Count visible messages in a room newer than the given id (all when None)."""
        query = select(func.count(Message.id)).where(
            Message.room_id == room_id,
            Message.is_deleted == False,  # noqa: E712
        )
        if message_id is not None:
            query = query.where(Message.id > message_id)
        result = await self.db.execute(query)
        return int(result.scalar() or 0)
