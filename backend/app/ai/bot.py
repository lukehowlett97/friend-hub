"""
Hub Bot — @hub mention handling, context building, response posting, usage logging.
"""
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.chat.events import OutgoingChatMessage, OutgoingTypingIndicator
from app.models.message import Message
from app.models.planning import DEFAULT_GROUP_SLUG, Group

if TYPE_CHECKING:
    from app.domains.chat.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

import re

BOT_SESSION_ID = "00000000-0000-0000-0000-000000000b07"
BOT_NICKNAME = "Hub Bot"

# Matches @username mentions in the bot's reply text.
_BOT_MENTION_RE = re.compile(r"@([a-zA-Z0-9_-]+)")
_BOT_PUSH_BODY_MAX = 120

# Prompts live in app.domains.ai.agent_runtime / hub_agent_service, both fed
# from app.domains.ai.capabilities — do not add a competing prompt here.


class HubBot:
    def __init__(self):
        # session_id -> list of monotonic timestamps within the last minute
        self._rate_buckets: dict[str, list[float]] = defaultdict(list)

    # ── Public entry point ────────────────────────────────────────────────────

    async def handle_hub_mention(
        self,
        user_content: str,
        user_nickname: str,
        user_session_id: str,
        connection_manager: "ConnectionManager",
        user_id: uuid.UUID | None = None,
        source_message_id: int | None = None,
        room_id: uuid.UUID | None = None,
    ) -> None:
        """Called as an asyncio background task after a user sends @hub."""
        from app.models.database import async_session_factory

        settings = get_settings()

        if not settings.ai_api_key:
            async with async_session_factory() as db:
                await self._post_error("AI is not configured yet.", db, connection_manager, room_id=room_id)
            return

        if not self._check_rate_limit(user_session_id, settings.ai_hub_rate_limit_per_minute):
            async with async_session_factory() as db:
                await self._post_error(
                    "You're sending @hub messages too fast — please wait a moment.",
                    db, connection_manager, room_id=room_id,
                )
            return

        # Strip @hub prefix when present; slash commands are passed through as-is
        prompt = user_content.strip()
        for prefix in ("@hub ", "@Hub ", "@HUB ", "@hub", "@Hub", "@HUB"):
            if prompt.lower().startswith(prefix.lower()):
                prompt = prompt[len(prefix):].strip()
                break

        async with async_session_factory() as db:
            try:
                await connection_manager.broadcast(
                    OutgoingTypingIndicator(
                        session_id=BOT_SESSION_ID,
                        nickname=BOT_NICKNAME,
                        is_typing=True,
                    ).dict()
                )

                from app.domains.ai.hub_agent_service import SharedHubBotService
                from app.domains.ai.summary_service import create_llm_client

                group = await self._get_default_group(db)
                llm_client = create_llm_client()
                service = SharedHubBotService(db=db, llm_client=llm_client)
                result = await service.process_query(
                    query=prompt,
                    user_nickname=user_nickname,
                    dry_run=False,
                    include_debug=False,
                    group_id=group.id if group else None,
                    user_id=user_id,
                    source="chat",
                    source_message_id=source_message_id,
                    room_id=room_id,
                )

                response_text = self._reply_with_draft_markers(result.reply, result.draft_actions)
                response_text = self._reply_with_item_markers(response_text, result.created_items)
                await db.commit()
                await self._post_response(response_text, db, connection_manager, room_id=room_id)
                await self._log_usage(
                    db,
                    model=getattr(llm_client, "model", settings.ai_default_chat_model),
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    user_id=user_id,
                    group_id=group.id if group else None,
                    command=result.command or "hub_mention",
                )

            except Exception:
                logger.exception("Hub Bot error handling mention from %s", user_session_id)
                await self._post_error(
                    "Sorry, I hit an error. Please try again in a moment.",
                    db, connection_manager, room_id=room_id,
                )
            finally:
                await connection_manager.broadcast(
                    OutgoingTypingIndicator(
                        session_id=BOT_SESSION_ID,
                        nickname=BOT_NICKNAME,
                        is_typing=False,
                    ).dict()
                )

    # ── Shared service helpers ────────────────────────────────────────────────

    async def _get_default_group(self, db: AsyncSession) -> Group | None:
        result = await db.execute(select(Group).where(Group.slug == DEFAULT_GROUP_SLUG))
        group = result.scalar_one_or_none()
        if group:
            return group
        group = Group(name="Friend Hub", slug=DEFAULT_GROUP_SLUG)
        db.add(group)
        await db.flush()
        return group

    def _reply_with_item_markers(self, reply: str, created_items: list[dict]) -> str:
        """Append inline card markers for items created by the bot this turn."""
        markers = []
        for item in created_items or []:
            item_type = item.get("item_type", "")
            source_id = item.get("source_id")
            short_id  = item.get("short_id", "")
            if item_type == "poll" and source_id:
                marker = f"[[agenda-poll:{source_id}]]"
            elif item_type == "event" and source_id:
                marker = f"[[hub-item-event:{source_id}]]"
            elif short_id:
                marker = f"[[hub-item:{short_id}]]"
            else:
                continue
            if marker not in reply:
                markers.append(marker)
        if not markers:
            return reply
        return "\n\n".join([reply.strip(), *markers]).strip()

    def _reply_with_draft_markers(self, reply: str, draft_actions: list[dict]) -> str:
        markers = []
        for draft in draft_actions or []:
            draft_id = draft.get("id")
            if draft_id:
                marker = f"[[ai-draft-action:{draft_id}]]"
                if marker not in reply:
                    markers.append(marker)
        if not markers:
            return reply
        return "\n\n".join([reply.strip(), *markers]).strip()

    # ── Posting ───────────────────────────────────────────────────────────────

    async def _post_response(
        self,
        text: str,
        db: AsyncSession,
        connection_manager: "ConnectionManager",
        room_id: uuid.UUID | None = None,
    ) -> None:
        bot_uuid = uuid.UUID(BOT_SESSION_ID)
        for chunk in _split_message(text):
            message = Message(
                user_session_id=bot_uuid,
                user_id=bot_uuid,
                content=chunk,
                created_at=datetime.utcnow(),
                room_id=room_id,
            )
            db.add(message)
            await db.commit()
            await db.refresh(message)

            await connection_manager.broadcast(
                OutgoingChatMessage(
                    session_id=BOT_SESSION_ID,
                    nickname=BOT_NICKNAME,
                    content=chunk,
                    timestamp=message.created_at,
                    message_id=message.id,
                    is_bot=True,
                    avatar_emoji="🤖",
                ).dict()
            )

            await self._notify_mentioned_users(
                chunk, db, connection_manager, message_id=message.id, room_id=room_id
            )

    async def _notify_mentioned_users(
        self,
        chunk: str,
        db: AsyncSession,
        connection_manager: "ConnectionManager",
        *,
        message_id: int,
        room_id: uuid.UUID | None = None,
    ) -> None:
        """Notify users @mentioned in a Hub Bot reply.

        Creates an in-app bell row, sends a real-time WS event, and fans out
        web push — all gated on the recipient's `hub_bot` preference. Best
        effort: failures are logged and never break the bot's post flow.
        """
        usernames = {m.lower() for m in _BOT_MENTION_RE.findall(chunk or "") if m}
        if not usernames:
            return

        try:
            from app.domains.chat.events import OutgoingNotification
            from app.domains.notifications.push_fanout import fanout_push_to_user_if_allowed
            from app.models.message import User
            from app.models.notification import Notification

            result = await db.execute(
                select(User.id).where(
                    User.username.isnot(None),
                    func.lower(User.username).in_(usernames),
                    User.is_active.is_(True),
                    User.is_bot.is_(False),
                )
            )
            user_ids = list(result.scalars().all())
            if not user_ids:
                return

            title = f"{BOT_NICKNAME} mentioned you"
            flat = " ".join((chunk or "").split())
            body = flat if len(flat) <= _BOT_PUSH_BODY_MAX else flat[: _BOT_PUSH_BODY_MAX - 1] + "…"

            for user_id in user_ids:
                notif = Notification(
                    user_id=user_id,
                    type="hub_bot",
                    title=title,
                    body=body,
                    target_type="message",
                    target_id=message_id,
                    room_id=room_id,
                )
                db.add(notif)
                await db.flush()

                await connection_manager.send_to_user_by_id(
                    str(user_id),
                    OutgoingNotification(
                        notification_id=notif.id,
                        notif_type="hub_bot",
                        title=title,
                        body=body,
                        target_type="message",
                        target_id=message_id,
                    ).dict(),
                )

                await fanout_push_to_user_if_allowed(
                    db,
                    user_id=user_id,
                    notif_type="hub_bot",
                    title=title,
                    body=body,
                    url=f"/chat?message={message_id}",
                    tag=f"fh-hub_bot-{message_id}",
                    data={
                        "notif_type": "hub_bot",
                        "target_type": "message",
                        "target_id": message_id,
                        "action_title": "Open chat",
                    },
                )

            await db.commit()
        except Exception as exc:  # noqa: BLE001 — bot notifications must not break posting
            logger.warning("Hub Bot mention notification failed: %s", exc)

    async def _post_error(
        self,
        text: str,
        db: AsyncSession,
        connection_manager: "ConnectionManager",
        room_id: uuid.UUID | None = None,
    ) -> None:
        await self._post_response(f"⚠️ {text}", db, connection_manager, room_id=room_id)

    # ── Usage logging ─────────────────────────────────────────────────────────

    async def _log_usage(
        self,
        db: AsyncSession,
        model: str,
        tokens_in: int,
        tokens_out: int,
        user_id: uuid.UUID | None = None,
        group_id: int | None = None,
        command: str | None = None,
    ) -> None:
        try:
            await db.execute(
                text(
                    "INSERT INTO ai_usage_log "
                    "(provider, model, feature, tokens_in, tokens_out, cost_cents, user_id, group_id, command) "
                    "VALUES (:provider, :model, :feature, :tokens_in, :tokens_out, :cost_cents, :user_id, :group_id, :command)"
                ),
                {
                    "provider": "openrouter",
                    "model": model,
                    "feature": command or "hub_mention",
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "cost_cents": 0,
                    "user_id": user_id,
                    "group_id": group_id,
                    "command": command,
                },
            )
            await db.commit()
        except Exception:
            logger.warning("Failed to log AI usage", exc_info=True)

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _check_rate_limit(self, session_id: str, max_per_minute: int) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        bucket = [t for t in self._rate_buckets[session_id] if t > cutoff]
        self._rate_buckets[session_id] = bucket
        if len(bucket) >= max_per_minute:
            return False
        self._rate_buckets[session_id].append(now)
        return True


_MSG_LIMIT = 900  # stay under the 1000-char DB constraint with headroom


def _split_message(text: str) -> list[str]:
    """Split a long bot reply into chunks that fit the message content limit.

    Tries to split on paragraph boundaries (double newline) first, then
    single newlines, then hard-cuts at the limit as a last resort.
    """
    if len(text) <= _MSG_LIMIT:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > _MSG_LIMIT:
        # Try paragraph break
        cut = remaining.rfind("\n\n", 0, _MSG_LIMIT)
        if cut == -1:
            # Try single newline
            cut = remaining.rfind("\n", 0, _MSG_LIMIT)
        if cut == -1:
            # Hard cut at last space
            cut = remaining.rfind(" ", 0, _MSG_LIMIT)
        if cut == -1:
            cut = _MSG_LIMIT
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        chunks.append(remaining)
    return [c for c in chunks if c]


# Module-level singleton shared across all WebSocket connections
hub_bot = HubBot()
