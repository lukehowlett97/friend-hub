"""Glue between the existing in-app Notification creation paths and Web Push.

`fanout_push_to_user` is intentionally tolerant: any failure logs and
returns. Push is best-effort — never let it break the request flow that
created the original Notification row.
"""
from __future__ import annotations

import logging
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.push_notification_service import get_push_service

from .preferences_repository import NotificationPreferencesRepository
from .push_repository import PushSubscriptionRepository

logger = logging.getLogger(__name__)

# Per-type Web Push delivery profiles: (urgency, ttl_seconds).
# Urgency "high" wakes Android from Doze; TTL is how long the push service
# queues the message for an offline device. Chat survives five days so a
# phone that was off over a weekend still gets the alert — the per-room
# Topic collapse means it only ever receives the latest message per room.
PUSH_PROFILES: dict[str, tuple[str, int]] = {
    "chat_messages": ("high", 432000),
    "chat_mentions": ("high", 432000),
    "hub_bot": ("high", 432000),
    "reminders": ("high", 86400),
}
DEFAULT_PUSH_PROFILE = ("normal", 86400)


def resolve_push_profile(notif_type: str | None) -> tuple[str, int]:
    return PUSH_PROFILES.get(notif_type or "", DEFAULT_PUSH_PROFILE)


async def fanout_push_to_user_if_allowed(
    db: AsyncSession,
    *,
    user_id,
    notif_type: str,
    title: str,
    body: str | None = None,
    url: str | None = None,
    icon: str | None = None,
    badge: str | None = None,
    tag: str | None = None,
    renotify: bool = False,
    data: dict | None = None,
    topic: str | None = None,
    urgency: str | None = None,
    ttl: int | None = None,
) -> None:
    """Fan out push to a user only if their preferences allow `notif_type`.

    Wraps `fanout_push_to_user` with a `should_send_push` check so callers
    don't have to repeat the per-user preference lookup. Best-effort: any
    failure logs and returns without touching the caller's flow.
    """
    try:
        prefs = NotificationPreferencesRepository(db)
        if not await prefs.should_send_push(user_id, notif_type):
            logger.debug("push suppressed by prefs for user %s (type=%s)", user_id, notif_type)
            return
    except Exception as exc:  # noqa: BLE001 — never let a pref lookup break push
        logger.warning("push preference check failed for user %s: %s", user_id, exc)
        return

    await fanout_push_to_user(
        db,
        user_id=user_id,
        notif_type=notif_type,
        title=title,
        body=body,
        url=url,
        icon=icon,
        badge=badge,
        tag=tag,
        renotify=renotify,
        data=data,
        topic=topic,
        urgency=urgency,
        ttl=ttl,
    )


async def fanout_push_to_user(
    db: AsyncSession,
    *,
    user_id,
    title: str,
    body: str | None = None,
    url: str | None = None,
    icon: str | None = None,
    badge: str | None = None,
    tag: str | None = None,
    renotify: bool = False,
    data: dict | None = None,
    notif_type: str | None = None,
    topic: str | None = None,
    urgency: str | None = None,
    ttl: int | None = None,
) -> None:
    """Send a push notification to every active subscription for a user.

    Urgency/TTL default to the per-type profile for `notif_type`; explicit
    arguments override the profile.
    """
    profile_urgency, profile_ttl = resolve_push_profile(notif_type)
    urgency = urgency or profile_urgency
    ttl = profile_ttl if ttl is None else ttl
    try:
        repo = PushSubscriptionRepository(db)
        subs = await repo.list_for_user(user_id)
        if not subs:
            logger.debug("no push subscriptions for user %s — skipping fanout", user_id)
            return

        logger.info(
            "fanning out push to %d subscriptions for user %s (type=%s urgency=%s ttl=%s)",
            len(subs), user_id, notif_type or "general", urgency, ttl,
        )
        service = get_push_service()
        results = await service.send_to_subscriptions(
            subs,
            title=title,
            body=body,
            url=url,
            icon=icon,
            badge=badge,
            tag=tag,
            renotify=renotify,
            data=data,
            notif_type=notif_type or "general",
            urgency=urgency,
            ttl=ttl,
            topic=topic,
        )

        for result in results:
            if result.is_gone:
                # Browser tossed the subscription — drop it so we stop trying.
                # Find the row by id and delete by endpoint.
                sub = next((s for s in subs if s.id == result.subscription_id), None)
                if sub:
                    await repo.delete_by_endpoint(sub.endpoint)
            elif result.success:
                await repo.mark_success(result.subscription_id)
            else:
                await repo.mark_failure(result.subscription_id)
    except Exception as exc:  # noqa: BLE001 — push must never break the caller
        logger.warning("push fanout failed for user %s: %s", user_id, exc)


async def fanout_push_to_users(
    db: AsyncSession,
    *,
    user_ids: Iterable,
    title: str,
    body: str | None = None,
    url: str | None = None,
    icon: str | None = None,
    badge: str | None = None,
    tag: str | None = None,
    renotify: bool = False,
    data: dict | None = None,
    notif_type: str | None = None,
    topic: str | None = None,
    urgency: str | None = None,
    ttl: int | None = None,
) -> None:
    for uid in user_ids:
        await fanout_push_to_user(
            db,
            user_id=uid,
            title=title,
            body=body,
            url=url,
            icon=icon,
            badge=badge,
            tag=tag,
            renotify=renotify,
            data=data,
            notif_type=notif_type,
            topic=topic,
            urgency=urgency,
            ttl=ttl,
        )
