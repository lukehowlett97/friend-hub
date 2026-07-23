"""
WebSocket message handler — routes incoming messages to typed handlers.
"""
import asyncio
import logging
from typing import Dict, Any, Callable, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from .events import (
    WebSocketEventType,
    OutgoingChatMessage,
    OutgoingOnlineUsers,
    OutgoingTypingIndicator,
    OutgoingPong,
    OutgoingError,
    OutgoingReactionUpdated,
    OutgoingMessageDeleted,
    OutgoingMessageEdited,
)
from .connection_manager import ConnectionManager
from app.services.chat_service import ChatService

logger = logging.getLogger(__name__)


class WebSocketMessageHandler:
    """Routes and processes incoming WebSocket messages."""

    def __init__(self, connection_manager: ConnectionManager):
        self.connection_manager = connection_manager
        self.handlers: Dict[str, Callable] = {
            WebSocketEventType.MESSAGE:         self._handle_chat_message,
            WebSocketEventType.PING:            self._handle_ping,
            WebSocketEventType.TYPING:          self._handle_typing,
            WebSocketEventType.STOP_TYPING:     self._handle_stop_typing,
            WebSocketEventType.TOGGLE_REACTION: self._handle_toggle_reaction,
            WebSocketEventType.DELETE_MESSAGE:  self._handle_delete_message,
            WebSocketEventType.EDIT_MESSAGE:    self._handle_edit_message,
            WebSocketEventType.VISIBILITY:      self._handle_visibility,
        }

    async def handle_message(
        self,
        message_type: str,
        data: Dict[str, Any],
        conn_id: str,
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        handler = self.handlers.get(message_type)
        if not handler:
            logger.warning("Unknown message type: %s", message_type)
            return OutgoingError(error=f"Unknown message type: {message_type}").dict()

        try:
            return await handler(data, conn_id, db)
        except Exception as e:
            logger.error("Error handling %s: %s", message_type, e)
            return OutgoingError(error="Server error occurred").dict()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_user(self, conn_id: str):
        user = self.connection_manager.get_user(conn_id)
        if user is None:
            raise RuntimeError(f"No authenticated user for conn {conn_id}")
        return user

    def _get_room_id(self, conn_id: str):
        room = self.connection_manager.get_room(conn_id)
        return room.id if room is not None else None

    # ── Chat message ─────────────────────────────────────────────────────────

    async def _handle_chat_message(self, data, conn_id, db):
        user = self._get_user(conn_id)
        user_sid = str(user.session_id)
        room_id = self._get_room_id(conn_id)

        content = data.get("content", "").strip()
        reply_to_id = data.get("reply_to_id")
        if not content:
            return None

        chat_service = ChatService(db)
        message, nickname, reply_to = await chat_service.save_message(
            user_sid, content, reply_to_id=reply_to_id, user_id=user.id, room_id=room_id,
        )

        await self.connection_manager.broadcast(
            OutgoingChatMessage(
                session_id=user_sid,
                nickname=nickname,
                username=getattr(user, "username", None),
                avatar_url=getattr(user, "avatar_url", None),
                avatar_emoji=getattr(user, "avatar_emoji", None),
                display_role=getattr(user, "display_role", None),
                role=getattr(getattr(user, "role", None), "value", getattr(user, "role", None)),
                content=content,
                timestamp=message.created_at,
                message_id=message.id,
                reply_to=reply_to,
            ).dict()
        )
        logger.info("Message %d broadcast from user %s", message.id, user_sid)

        asyncio.create_task(
            _push_chat_notifications(
                sender_id=str(user.id) if user.id else None,
                sender_nickname=nickname,
                sender_avatar_url=getattr(user, "avatar_url", None),
                content=content,
                message_id=message.id,
                room_id=room_id,
                room_name=getattr(self.connection_manager.get_room(conn_id), "name", None),
                visible_user_ids=self.connection_manager.get_visible_user_ids(),
            )
        )

        if _is_hub_mention(content):
            from app.ai.bot import hub_bot
            asyncio.create_task(
                hub_bot.handle_hub_mention(
                    content,
                    nickname,
                    user_sid,
                    self.connection_manager,
                    user_id=user.id,
                    source_message_id=message.id,
                    room_id=room_id,
                )
            )

    # ── Typing indicators ─────────────────────────────────────────────────────

    async def _handle_typing(self, data, conn_id, db):
        user = self._get_user(conn_id)
        user_sid = str(user.session_id)
        await self.connection_manager.broadcast_except_user(
            OutgoingTypingIndicator(
                session_id=user_sid,
                nickname=user.nickname,
                is_typing=True,
            ).dict(),
            user_sid,
        )

    async def _handle_stop_typing(self, data, conn_id, db):
        user = self._get_user(conn_id)
        user_sid = str(user.session_id)
        await self.connection_manager.broadcast_except_user(
            OutgoingTypingIndicator(
                session_id=user_sid,
                nickname=user.nickname,
                is_typing=False,
            ).dict(),
            user_sid,
        )

    # ── Visibility ────────────────────────────────────────────────────────────

    async def _handle_visibility(self, data, conn_id, db):
        """Client tells us whether its tab is currently in the foreground.

        We store the bit on the connection so chat-message push fanout can
        skip live viewers and target backgrounded tabs / sleeping devices.
        """
        self.connection_manager.set_visibility(conn_id, bool(data.get("visible", True)))

    # ── Ping ──────────────────────────────────────────────────────────────────

    async def _handle_ping(self, data, conn_id, db):
        user = self._get_user(conn_id)
        await ChatService(db).update_user_last_seen(str(user.session_id))
        return OutgoingPong().dict()

    # ── Reactions ─────────────────────────────────────────────────────────────

    async def _handle_toggle_reaction(self, data, conn_id, db):
        user = self._get_user(conn_id)
        user_sid = str(user.session_id)

        message_id = data.get("message_id")
        emoji = data.get("emoji", "").strip()
        if not message_id or not emoji:
            return OutgoingError(error="Missing message_id or emoji").dict()

        chat_service = ChatService(db)
        reactions = await chat_service.toggle_reaction(message_id, user_sid, emoji, user_id=user.id)

        await self.connection_manager.broadcast(
            OutgoingReactionUpdated(message_id=message_id, reactions=reactions).dict()
        )
        logger.info("Reaction toggled on message %d by user %s", message_id, user_sid)

    # ── Delete message ────────────────────────────────────────────────────────

    async def _handle_delete_message(self, data, conn_id, db):
        user = self._get_user(conn_id)
        user_sid = str(user.session_id)

        message_id = data.get("message_id")
        if not message_id:
            return OutgoingError(error="message_id required").dict()

        chat_service = ChatService(db)
        if not await chat_service.delete_message(message_id, user_sid):
            return OutgoingError(error="Cannot delete this message").dict()

        await self.connection_manager.broadcast(
            OutgoingMessageDeleted(message_id=message_id, session_id=user_sid).dict()
        )
        logger.info("Message %d soft-deleted by user %s", message_id, user_sid)

    # ── Edit message ──────────────────────────────────────────────────────────

    async def _handle_edit_message(self, data, conn_id, db):
        user = self._get_user(conn_id)
        user_sid = str(user.session_id)

        message_id  = data.get("message_id")
        new_content = data.get("content", "").strip()

        if not message_id or not new_content:
            return OutgoingError(error="message_id and content required").dict()
        if len(new_content) > 1000:
            return OutgoingError(error="Message too long (max 1000 chars)").dict()

        chat_service = ChatService(db)
        message = await chat_service.edit_message(message_id, user_sid, new_content)
        if not message:
            return OutgoingError(error="Cannot edit this message").dict()

        await self.connection_manager.broadcast(
            OutgoingMessageEdited(
                message_id=message_id,
                content=new_content,
                edited_at=message.edited_at.isoformat() if message.edited_at else "",
            ).dict()
        )
        logger.info("Message %d edited by user %s", message_id, user_sid)

    # ── Extension points ──────────────────────────────────────────────────────

    def add_handler(self, message_type: str, handler: Callable):
        self.handlers[message_type] = handler

    def remove_handler(self, message_type: str):
        self.handlers.pop(message_type, None)


# ── Module-level helpers ─────────────────────────────────────────────────────

import re

_MENTION_RE = re.compile(r"@([a-zA-Z0-9_-]+)")
_HUB_MENTION_RE = re.compile(r"(^|\s)@hub\b", re.IGNORECASE)
_SLASH_CMD_RE = re.compile(r"(^|\s)/(event|poll|image|idea|remind|summarise|summarize|search|catchup)\b", re.IGNORECASE)
_PUSH_BODY_MAX = 120


def _truncate_for_push(content: str) -> str:
    """Single-line preview for the push body."""
    flat = " ".join(content.split())
    return flat if len(flat) <= _PUSH_BODY_MAX else flat[: _PUSH_BODY_MAX - 1] + "…"


def _is_hub_mention(content: str) -> bool:
    c = content or ""
    return bool(_HUB_MENTION_RE.search(c) or _SLASH_CMD_RE.search(c))


async def _push_mention_notifications(
    *,
    sender_id: str | None,
    sender_nickname: str,
    content: str,
    message_id: int,
) -> None:
    """Push chat @mentions to active members of the current chat group."""
    await _push_chat_notifications(
        sender_id=sender_id,
        sender_nickname=sender_nickname,
        content=content,
        message_id=message_id,
        mention_only=True,
    )


async def _push_chat_notifications(
    *,
    sender_id: str | None,
    sender_nickname: str,
    content: str,
    message_id: int,
    sender_avatar_url: str | None = None,
    room_id=None,
    room_name: str | None = None,
    visible_user_ids: set[str] | None = None,
    mention_only: bool = False,
) -> None:
    """Push chat messages to room members who are not already viewing chat.

    Mentions get a more specific title/payload. Non-mentioned users receive a
    generic chat-message push so mobile/background users still see chat.
    """
    from sqlalchemy import func, select

    from app.domains.notifications.push_fanout import fanout_push_to_user_if_allowed
    from app.models.database import async_session_factory
    from app.models.member import GroupMember
    from app.models.message import User
    from app.models.planning import DEFAULT_GROUP_SLUG, Group
    from app.models.room import RoomMembership

    mentioned_usernames = {m.lower() for m in _MENTION_RE.findall(content) if m}
    if mention_only and not mentioned_usernames:
        return

    body = _truncate_for_push(content)
    url = f"/chat?message={message_id}"
    room_label = (room_name or "Friend Hub").strip() or "Friend Hub"
    icon = sender_avatar_url or "/icons/notification-icon.svg"
    badge = "/icons/notification-badge.svg"
    sent_user_ids = set()
    visible_user_ids = {str(uid) for uid in (visible_user_ids or set())}

    try:
        async with async_session_factory() as db:
            filters = [
                User.is_active.is_(True),
                User.hidden_from_member_list.is_(False),
                User.is_test_user.is_(False),
                User.is_bot.is_(False),
                User.status.notin_(["deactivated", "archived", "deleted"]),
                User.user_type.notin_(["test", "system", "bot"]),
            ]
            if mention_only:
                filters.extend([
                    User.username.isnot(None),
                    func.lower(User.username).in_(mentioned_usernames),
                ])

            if room_id is not None:
                member_stmt = (
                    select(User.id, User.username)
                    .join(RoomMembership, User.id == RoomMembership.user_id)
                    .where(RoomMembership.room_id == room_id, *filters)
                )
            else:
                group_result = await db.execute(
                    select(Group.id).where(Group.slug == DEFAULT_GROUP_SLUG)
                )
                group_id = group_result.scalar_one_or_none()
                if group_id is None:
                    logger.warning("chat push skipped: default group not found")
                    return

                member_stmt = (
                    select(User.id, User.username)
                    .join(GroupMember, User.session_id == GroupMember.user_session_id)
                    .where(GroupMember.group_id == group_id, *filters)
                )

            member_result = await db.execute(member_stmt)
            rows = member_result.all()

            for user_id, username in rows:
                uid_str = str(user_id)
                if (
                    uid_str in sent_user_ids
                    or uid_str in visible_user_ids
                    or (sender_id and uid_str == sender_id)
                ):
                    continue

                is_mention = bool(username and username.lower() in mentioned_usernames)
                if mention_only and not is_mention:
                    continue

                await fanout_push_to_user_if_allowed(
                    db,
                    user_id=user_id,
                    notif_type="chat_mentions" if is_mention else "chat_messages",
                    title=(
                        f"{sender_nickname} mentioned you in {room_label}"
                        if is_mention
                        else f"{sender_nickname} in {room_label}"
                    ),
                    body=body,
                    url=url,
                    icon=icon,
                    badge=badge,
                    tag=f"fh-chat-{room_id or 'main'}-{message_id}",
                    renotify=is_mention,
                    # Collapse pending (undelivered) chat pushes per room so a
                    # reconnecting device only gets the latest. Mentions keep
                    # no topic — every pending mention should be delivered.
                    topic=None if is_mention else f"fh-chat-{room_id or 'main'}",
                    data={
                        "notif_type": "mention" if is_mention else "chat_message",
                        "target_type": "message",
                        "target_id": message_id,
                        "sender_id": sender_id,
                        "sender_nickname": sender_nickname,
                        "room_id": str(room_id) if room_id else None,
                        "room_name": room_name,
                        "action_title": "Open chat",
                    },
                )
                sent_user_ids.add(uid_str)
    except Exception as exc:  # noqa: BLE001 — push must never break the WS flow
        logger.warning("chat push fanout failed: %s", exc)
