"""
Message service — business logic for chat messages.
"""
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from .repository import MessageRepository
from app.models.message import Message, User
from app.domains.users.repository import UserRepository
from app.domains.reactions.repository import ReactionRepository
from app.domains.hub_items.references import find_hub_item_references

logger = logging.getLogger(__name__)

REPLY_PREVIEW_LENGTH = 100
BOT_SESSION_ID = "00000000-0000-0000-0000-000000000b07"
BOT_NICKNAME = "Hub Bot"


def _effective_user(msg: Optional[Message], user: Optional[User], linked_user: Optional[User] = None) -> Optional[User]:
    if msg is not None and getattr(msg, "is_imported", False) and linked_user is not None:
        return linked_user
    return user


def _build_reply_to(
    reply_msg: Optional[Message],
    reply_user: Optional[User],
    reply_linked_user: Optional[User] = None,
) -> Optional[dict]:
    """Shape a reply-to dict for API / WS payloads, or None if no reply."""
    if reply_msg is None:
        return None
    effective_user = _effective_user(reply_msg, reply_user, reply_linked_user)
    if reply_msg.is_deleted:
        content = "[deleted]"
    else:
        c = reply_msg.content
        content = c[:REPLY_PREVIEW_LENGTH] + ("…" if len(c) > REPLY_PREVIEW_LENGTH else "")
    return {
        "id": reply_msg.id,
        "content": content,
        "nickname": effective_user.nickname if effective_user else _fallback_nickname(reply_msg),
    }


def _fallback_nickname(msg: Optional[Message]) -> str:
    if msg is not None and str(getattr(msg, "user_session_id", "")) == BOT_SESSION_ID:
        return BOT_NICKNAME
    return "Unknown"


def _fallback_is_bot(msg: Optional[Message]) -> bool:
    return msg is not None and str(getattr(msg, "user_session_id", "")) == BOT_SESSION_ID


class MessageService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.message_repo  = MessageRepository(db)
        self.user_repo     = UserRepository(db)
        self.reaction_repo = ReactionRepository(db)

    async def save_message(
        self,
        session_id: str,
        content: str,
        reply_to_id: Optional[int] = None,
        user_id=None,
        room_id=None,
    ) -> Tuple[Message, str, Optional[dict]]:
        """
        Persist a new message and return (message, nickname, reply_to_dict).
        reply_to_dict is None when this is not a reply.
        """
        content = content.strip()
        if not content:
            raise ValueError("Message content cannot be empty")

        message = await self.message_repo.create_message(
            session_id, content, reply_to_id=reply_to_id, user_id=user_id, room_id=room_id,
        )

        user = await self.user_repo.get_by_session_id(session_id)
        nickname = user.nickname if user else session_id

        reply_to = None
        if reply_to_id:
            original = await self.message_repo.get_message_by_id(reply_to_id)
            if original:
                orig_user = await self.user_repo.get_by_session_id(
                    str(original.user_session_id)
                )
                reply_to = _build_reply_to(original, orig_user)

        return message, nickname, reply_to

    async def get_recent_messages(
        self,
        limit: int = 50,
        offset: int = 0,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        room_id=None,
    ) -> List[dict]:
        """Return chronologically-ordered messages with reply_to and reactions."""
        rows = await self.message_repo.get_recent_messages_with_users(
            limit=limit,
            offset=offset,
            start_at=start_at,
            end_at=end_at,
            room_id=room_id,
        )

        messages = self._rows_to_payloads(rows)

        # Reverse to chronological order before batch-fetching reactions.
        messages.reverse()
        await self._attach_reactions(messages)
        return messages

    async def get_message_context(
        self,
        message_id: int,
        before: int = 25,
        after: int = 25,
        room_id=None,
    ) -> List[dict]:
        rows = await self.message_repo.get_message_context_with_users(
            message_id,
            before=before,
            after=after,
            room_id=room_id,
        )
        messages = self._rows_to_payloads(rows)
        await self._attach_reactions(messages)
        return messages

    def _rows_to_payloads(self, rows) -> List[dict]:
        messages = []
        for row in rows:
            if len(row) >= 6:
                msg, user, linked_user, reply_msg, reply_user, reply_linked_user = row[:6]
            else:
                msg, user, reply_msg, reply_user = row
                linked_user = None
                reply_linked_user = None
            effective_user = _effective_user(msg, user, linked_user)
            effective_user_id = getattr(effective_user, "id", None) if effective_user else None
            effective_session_id = getattr(effective_user, "session_id", None) if effective_user else None
            message_user_id = getattr(msg, "user_id", None)
            messages.append({
                "id": msg.id,
                "session_id": str(effective_session_id or msg.user_session_id),
                "user_id": str(effective_user_id) if effective_user_id else str(message_user_id) if message_user_id else None,
                "imported_identity_id": str(msg.imported_identity_id) if getattr(msg, "imported_identity_id", None) else None,
                "nickname": effective_user.nickname if effective_user else _fallback_nickname(msg),
                "username": getattr(effective_user, "username", None) if effective_user else None,
                "is_bot": bool(effective_user.is_bot) if effective_user else _fallback_is_bot(msg),
                "avatar_url": effective_user.avatar_url if effective_user else None,
                "avatar_emoji": getattr(effective_user, "avatar_emoji", None) if effective_user else None,
                "display_role": getattr(effective_user, "display_role", None) if effective_user else None,
                "role": getattr(getattr(effective_user, "role", None), "value", getattr(effective_user, "role", None)) if effective_user else None,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                "is_deleted": bool(msg.is_deleted),
                "is_imported": bool(getattr(msg, "is_imported", False)),
                "is_pinned": bool(getattr(msg, "is_pinned", False)),
                "reply_to": _build_reply_to(reply_msg, reply_user, reply_linked_user),
                "hub_item_id": str(msg.hub_item_id) if msg.hub_item_id else None,
                "hub_item_references": find_hub_item_references(msg.content),
                "reactions": [],
                "type": "chat",
            })
        return messages

    async def _attach_reactions(self, messages: List[dict]) -> None:
        if not messages:
            return
        message_ids = [m["id"] for m in messages]
        reactions_map = await self.reaction_repo.get_reactions_for_messages(message_ids)
        for m in messages:
            m["reactions"] = reactions_map.get(m["id"], [])

    async def get_message_by_id(self, message_id: int, room_id=None) -> Optional[Message]:
        return await self.message_repo.get_message_by_id(message_id, room_id=room_id)

    async def get_messages_by_user(
        self,
        session_id: str,
        limit: int = 50,
        offset: int = 0,
        imported_identity_ids: list | None = None,
        source: str = "all",
    ) -> List[dict]:
        rows = await self.message_repo.get_messages_by_user_with_users(
            session_id,
            limit,
            offset,
            imported_identity_ids=imported_identity_ids,
            source=source,
        )
        messages = self._rows_to_payloads(rows)
        await self._attach_reactions(messages)
        return messages

    async def toggle_reaction(
        self, message_id: int, session_id: str, emoji: str, user_id=None
    ) -> List[dict]:
        """Toggle a reaction on a message. Returns updated reaction list."""
        return await self.reaction_repo.toggle_reaction(message_id, session_id, emoji, user_id=user_id)

    async def delete_message(self, message_id: int, requesting_session_id: str) -> bool:
        """Soft-delete. Returns False if not found or requester isn't owner."""
        return await self.message_repo.soft_delete_message(message_id, requesting_session_id)

    async def edit_message(
        self, message_id: int, requesting_session_id: str, new_content: str
    ) -> Optional[Message]:
        """Edit message content. Returns updated Message or None on failure."""
        new_content = new_content.strip()
        if not new_content or len(new_content) > 1000:
            return None
        return await self.message_repo.edit_message(message_id, requesting_session_id, new_content)
