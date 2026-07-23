"""
Web Push delivery.

pywebpush is a synchronous library; we run each call in a worker thread so
the event loop isn't blocked. The service itself doesn't touch the DB —
the repository owns subscription lifecycle. Callers feed in a list of
subscriptions and we report which ones the push service rejected as gone
(404/410) so they can be cleaned up.

Delivery semantics (RFC 8030):
- TTL: how long the push service queues the message for an offline device.
  pywebpush defaults to 0 ("deliver now or drop"), which silently loses
  pushes to dozing/offline Android devices — always pass an explicit TTL.
- Urgency: "high" wakes Android from Doze; "normal" may be deferred until
  the next maintenance window.
- Topic: pending (undelivered) messages with the same topic are collapsed
  so a reconnecting device only gets the latest one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from app.config import get_settings
from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)

DEFAULT_URGENCY = "normal"
DEFAULT_TTL = 86400

# Topic header values must be at most 32 characters from the base64url set.
_TOPIC_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_-]")


def sanitize_topic(topic: str) -> str:
    return _TOPIC_UNSAFE_RE.sub("-", topic)[:32]


@dataclass
class PushDeliveryResult:
    subscription_id: int
    success: bool
    is_gone: bool  # True when the push service says the endpoint is dead.
    status_code: Optional[int] = None


class PushNotificationService:
    def __init__(self):
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.vapid_private_key and self.settings.vapid_public_key)

    async def send_to_subscriptions(
        self,
        subscriptions: Iterable[PushSubscription],
        *,
        title: str,
        body: Optional[str] = None,
        url: Optional[str] = None,
        icon: Optional[str] = None,
        badge: Optional[str] = None,
        tag: Optional[str] = None,
        renotify: bool = False,
        data: Optional[dict] = None,
        notif_type: str = "general",
        urgency: str = DEFAULT_URGENCY,
        ttl: int = DEFAULT_TTL,
        topic: Optional[str] = None,
    ) -> List[PushDeliveryResult]:
        if not self.is_configured:
            logger.warning("VAPID keys not configured; push delivery skipped. Set VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY in .env")
            return []

        payload = {
            "title": title,
            "body": body or "",
            "icon": icon or "/icons/notification-icon.svg",
            "badge": badge or "/icons/notification-badge.svg",
            "data": {"url": url} if url else {},
            "renotify": renotify,
        }
        if tag:
            payload["tag"] = tag
        if data:
            payload["data"] = {**payload["data"], **data}
        payload_json = json.dumps(payload)

        headers: Dict[str, str] = {"Urgency": urgency}
        if topic:
            headers["Topic"] = sanitize_topic(topic)

        tasks = [
            self._send_one(sub, payload_json, headers=headers, ttl=ttl,
                           notif_type=notif_type, urgency=urgency)
            for sub in subscriptions
        ]
        return await asyncio.gather(*tasks)

    async def _send_one(
        self,
        sub: PushSubscription,
        payload_json: str,
        *,
        headers: Dict[str, str],
        ttl: int,
        notif_type: str,
        urgency: str,
    ) -> PushDeliveryResult:
        return await asyncio.to_thread(
            self._send_sync, sub, payload_json,
            headers=headers, ttl=ttl, notif_type=notif_type, urgency=urgency,
        )

    def _send_sync(
        self,
        sub: PushSubscription,
        payload_json: str,
        *,
        headers: Dict[str, str],
        ttl: int,
        notif_type: str,
        urgency: str,
    ) -> PushDeliveryResult:
        # Lazy import — pywebpush isn't installed in test envs.
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            logger.warning("pywebpush not installed; cannot send push notifications")
            return PushDeliveryResult(sub.id, success=False, is_gone=False)

        endpoint_host = urlparse(sub.endpoint).netloc

        def log_result(level: int, success: bool, status: Optional[int], extra: str = "") -> None:
            logger.log(
                level,
                "push delivery: user_id=%s subscription_id=%s endpoint_host=%s "
                "type=%s urgency=%s ttl=%s success=%s status=%s%s",
                sub.user_id, sub.id, endpoint_host,
                notif_type, urgency, ttl, success, status, extra,
            )

        try:
            response = webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
                },
                data=payload_json,
                vapid_private_key=self.settings.vapid_private_key,
                vapid_claims={"sub": self.settings.vapid_subject},
                ttl=ttl,
                headers=dict(headers),
            )
            status = getattr(response, "status_code", None)
            log_result(logging.INFO, True, status)
            return PushDeliveryResult(sub.id, success=True, is_gone=False, status_code=status)
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            # 404/410 means the browser has removed the subscription.
            is_gone = status in (404, 410)
            if is_gone:
                log_result(logging.INFO, False, status, " (endpoint gone — will clean up)")
            else:
                log_result(logging.WARNING, False, status, f" error={exc}")
            return PushDeliveryResult(sub.id, success=False, is_gone=is_gone, status_code=status)
        except Exception as exc:  # noqa: BLE001 — defensive, log and move on
            log_result(logging.ERROR, False, None, f" unexpected_error={exc}")
            return PushDeliveryResult(sub.id, success=False, is_gone=False)


_service: Optional[PushNotificationService] = None


def get_push_service() -> PushNotificationService:
    global _service
    if _service is None:
        _service = PushNotificationService()
    return _service
