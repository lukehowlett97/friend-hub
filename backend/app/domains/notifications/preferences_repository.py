"""Repository for per-user notification preferences."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification_preference import NotificationPreference

logger = logging.getLogger(__name__)

PREFERENCE_FIELDS = [
    "chat_messages",
    "chat_mentions",
    "polls",
    "events",
    "reminders",
    "comments",
    "reactions",
    "hub_bot",
    "push_enabled",
    "email_enabled",
]


class NotificationPreferencesRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create(self, user_id) -> NotificationPreference:
        """Get preferences for a user, creating defaults if none exist."""
        result = await self.db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        prefs = result.scalar_one_or_none()
        if prefs:
            return prefs

        now = datetime.utcnow()
        stmt = (
            insert(NotificationPreference)
            .values(user_id=user_id)
            .returning(NotificationPreference)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        prefs = result.scalar_one()
        logger.info("created default notification preferences for user %s", user_id)
        return prefs

    async def update(self, user_id, updates: dict) -> NotificationPreference:
        """Update preference fields. Only recognised fields are applied."""
        valid = {k: v for k, v in updates.items() if k in PREFERENCE_FIELDS and isinstance(v, bool)}
        if not valid:
            prefs = await self.get_or_create(user_id)
            return prefs

        valid["updated_at"] = datetime.utcnow()
        stmt = (
            insert(NotificationPreference)
            .values(user_id=user_id, **{k: v for k, v in valid.items() if k != "updated_at"})
            .on_conflict_do_update(
                index_elements=[NotificationPreference.user_id],
                set_=valid,
            )
            .returning(NotificationPreference)
        )
        result = await self.db.execute(stmt)
        await self.db.commit()
        prefs = result.scalar_one()
        logger.info("updated notification preferences for user %s: %s", user_id, set(valid.keys()) - {"updated_at"})
        return prefs

    async def should_send_push(self, user_id, notif_type: str) -> bool:
        """Check if a push notification of the given type should be sent.

        notif_type should be one of: chat_messages, chat_mentions, polls,
        events, reminders, comments, reactions, hub_bot.
        """
        prefs = await self.get_or_create(user_id)
        if not prefs.push_enabled:
            return False

        field_map = {
            "chat_messages": "chat_messages",
            "new_message": "chat_messages",
            "message": "chat_messages",
            "chat_mentions": "chat_mentions",
            "new_poll": "polls",
            "polls": "polls",
            "new_event": "events",
            "events": "events",
            "reminder": "reminders",
            "reminders": "reminders",
            "comment": "comments",
            "comments": "comments",
            "reaction": "reactions",
            "reactions": "reactions",
            "hub_bot": "hub_bot",
        }
        field = field_map.get(notif_type)
        if field is None:
            return True  # unknown types default to allowed

        return getattr(prefs, field, True)

    def preference_payload(self, prefs: NotificationPreference) -> dict:
        """Serialize preferences to a JSON-safe dict."""
        return {
            "chat_messages": prefs.chat_messages,
            "chat_mentions": prefs.chat_mentions,
            "polls": prefs.polls,
            "events": prefs.events,
            "reminders": prefs.reminders,
            "comments": prefs.comments,
            "reactions": prefs.reactions,
            "hub_bot": prefs.hub_bot,
            "push_enabled": prefs.push_enabled,
            "email_enabled": prefs.email_enabled,
        }