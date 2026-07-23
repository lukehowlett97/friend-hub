"""
Message repository for data access operations.
"""
import logging
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy import or_, select, asc, desc
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.imported_identity import ImportedIdentity
from app.models.message import Message, User

logger = logging.getLogger(__name__)


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_message(
        self,
        session_id: str,
        content: str,
        reply_to_id: Optional[int] = None,
        user_id=None,
        room_id=None,
    ) -> Message:
        message = Message(
            user_session_id=session_id,
            user_id=user_id,
            content=content,
            created_at=datetime.utcnow(),
            reply_to_id=reply_to_id,
            room_id=room_id,
        )
        self.db.add(message)
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def get_recent_messages_with_users(
        self,
        limit: int = 50,
        offset: int = 0,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        room_id=None,
    ) -> List[Tuple]:
        """
        Returns rows of (Message, User, ReplyMessage|None, ReplyUser|None).
        Ordered newest-first; callers reverse for chronological display.
        """
        ReplyMsg  = aliased(Message)
        ReplyUser = aliased(User)
        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        ReplyLinkedIdentity = aliased(ImportedIdentity)
        ReplyLinkedUser = aliased(User)

        query = (
            select(Message, User, LinkedUser, ReplyMsg, ReplyUser, ReplyLinkedUser)
            .outerjoin(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .outerjoin(ReplyMsg,  Message.reply_to_id == ReplyMsg.id)
            .outerjoin(ReplyUser, ReplyMsg.user_session_id == ReplyUser.session_id)
            .outerjoin(ReplyLinkedIdentity, ReplyMsg.imported_identity_id == ReplyLinkedIdentity.id)
            .outerjoin(ReplyLinkedUser, ReplyLinkedIdentity.linked_user_id == ReplyLinkedUser.id)
            .order_by(desc(Message.created_at))
        )
        if room_id is not None:
            query = query.where(Message.room_id == room_id)
        if start_at is not None:
            query = query.where(Message.created_at >= start_at)
        if end_at is not None:
            query = query.where(Message.created_at < end_at)

        result = await self.db.execute(query.limit(limit).offset(offset))
        return result.fetchall()

    async def get_message_context_with_users(
        self,
        message_id: int,
        before: int = 25,
        after: int = 25,
        room_id=None,
    ) -> List[Tuple]:
        """
        Return rows around a target message in chronological order.
        """
        target = await self.get_message_by_id(message_id, room_id=room_id)
        if target is None:
            return []
        target_created_at = target.created_at
        if target_created_at and target_created_at.tzinfo is not None:
            target_created_at = target_created_at.replace(tzinfo=None)

        older_where = Message.created_at <= target_created_at
        newer_where = Message.created_at > target_created_at
        if room_id is not None:
            older_where = older_where & (Message.room_id == room_id)
            newer_where = newer_where & (Message.room_id == room_id)

        older = await self._message_rows(
            where_clause=older_where,
            order_by=desc(Message.created_at),
            limit=before + 1,
        )
        newer = await self._message_rows(
            where_clause=newer_where,
            order_by=asc(Message.created_at),
            limit=after,
        )
        return list(reversed(older)) + newer

    async def get_messages_in_id_range(
        self,
        start_id: int,
        end_id: int,
        room_id=None,
        limit: int = 500,
    ) -> List[Tuple]:
        """Return joined rows for messages with start_id <= id <= end_id, oldest first."""
        where_clause = (Message.id >= start_id) & (Message.id <= end_id)
        if room_id is not None:
            where_clause = where_clause & (Message.room_id == room_id)
        return await self._message_rows(
            where_clause=where_clause,
            order_by=asc(Message.id),
            limit=limit,
        )

    async def _message_rows(self, *, where_clause, order_by, limit: int) -> List[Tuple]:
        ReplyMsg  = aliased(Message)
        ReplyUser = aliased(User)
        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        ReplyLinkedIdentity = aliased(ImportedIdentity)
        ReplyLinkedUser = aliased(User)
        result = await self.db.execute(
            select(Message, User, LinkedUser, ReplyMsg, ReplyUser, ReplyLinkedUser, LinkedIdentity)
            .outerjoin(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .outerjoin(ReplyMsg, Message.reply_to_id == ReplyMsg.id)
            .outerjoin(ReplyUser, ReplyMsg.user_session_id == ReplyUser.session_id)
            .outerjoin(ReplyLinkedIdentity, ReplyMsg.imported_identity_id == ReplyLinkedIdentity.id)
            .outerjoin(ReplyLinkedUser, ReplyLinkedIdentity.linked_user_id == ReplyLinkedUser.id)
            .where(where_clause)
            .order_by(order_by)
            .limit(limit)
        )
        return result.fetchall()

    async def get_message_by_id(self, message_id: int, room_id=None) -> Optional[Message]:
        query = select(Message).where(Message.id == message_id)
        if room_id is not None:
            query = query.where(Message.room_id == room_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def soft_delete_message(
        self, message_id: int, requesting_session_id: str
    ) -> bool:
        """
        Soft-delete: marks message as deleted and replaces content.
        Keeps the row so reply-to chains remain intact.
        Returns False if message not found or requester is not the owner.
        """
        message = await self.get_message_by_id(message_id)
        if not message:
            return False
        if str(message.user_session_id) != str(requesting_session_id):
            return False
        if message.is_deleted:
            return False  # already deleted

        message.is_deleted = True
        message.content = "[message deleted]"
        await self.db.commit()
        return True

    async def edit_message(
        self, message_id: int, requesting_session_id: str, new_content: str
    ) -> Optional[Message]:
        """
        Update message content. Returns the updated message, or None if the
        message doesn't exist, the requester isn't the owner, or it's deleted.
        """
        message = await self.get_message_by_id(message_id)
        if not message:
            return None
        if str(message.user_session_id) != str(requesting_session_id):
            return None
        if message.is_deleted:
            return None

        message.content = new_content
        message.edited_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def get_messages_by_user(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.user_session_id == session_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_messages_by_user_with_users(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        imported_identity_ids: list | None = None,
        source: str = "all",
    ) -> List[Tuple]:
        ReplyMsg = aliased(Message)
        ReplyUser = aliased(User)
        LinkedIdentity = aliased(ImportedIdentity)
        LinkedUser = aliased(User)
        ReplyLinkedIdentity = aliased(ImportedIdentity)
        ReplyLinkedUser = aliased(User)
        if source == "current":
            where_clause = Message.user_session_id == session_id
            where_clause = where_clause & Message.is_imported.is_(False)
        elif source == "imported":
            if not imported_identity_ids:
                return []
            where_clause = Message.imported_identity_id.in_(imported_identity_ids)
        else:
            filters = [Message.user_session_id == session_id]
            if imported_identity_ids:
                filters.append(Message.imported_identity_id.in_(imported_identity_ids))
            where_clause = or_(*filters)

        query = (
            select(Message, User, LinkedUser, ReplyMsg, ReplyUser, ReplyLinkedUser)
            .outerjoin(User, Message.user_session_id == User.session_id)
            .outerjoin(LinkedIdentity, Message.imported_identity_id == LinkedIdentity.id)
            .outerjoin(LinkedUser, LinkedIdentity.linked_user_id == LinkedUser.id)
            .outerjoin(ReplyMsg, Message.reply_to_id == ReplyMsg.id)
            .outerjoin(ReplyUser, ReplyMsg.user_session_id == ReplyUser.session_id)
            .outerjoin(ReplyLinkedIdentity, ReplyMsg.imported_identity_id == ReplyLinkedIdentity.id)
            .outerjoin(ReplyLinkedUser, ReplyLinkedIdentity.linked_user_id == ReplyLinkedUser.id)
            .where(where_clause)
            .order_by(desc(Message.created_at))
        )

        result = await self.db.execute(query.limit(limit).offset(offset))
        return result.fetchall()
