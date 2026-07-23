"""Repository for Web Push subscriptions."""
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push_subscription import PushSubscription

logger = logging.getLogger(__name__)


class PushSubscriptionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert(
        self,
        *,
        user_id,
        endpoint: str,
        p256dh_key: str,
        auth_key: str,
        user_agent: Optional[str] = None,
    ) -> PushSubscription:
        """Insert or refresh a subscription. (user_id, endpoint) is unique."""
        now = datetime.utcnow()
        stmt = insert(PushSubscription).values(
            user_id=user_id,
            endpoint=endpoint,
            p256dh_key=p256dh_key,
            auth_key=auth_key,
            user_agent=user_agent,
            created_at=now,
        ).on_conflict_do_update(
            index_elements=[PushSubscription.user_id, PushSubscription.endpoint],
            set_={
                "p256dh_key": p256dh_key,
                "auth_key": auth_key,
                "user_agent": user_agent,
            },
        ).returning(PushSubscription)

        result = await self.db.execute(stmt)
        await self.db.commit()
        sub = result.scalar_one()
        logger.info("push subscription upserted: user_id=%s endpoint=%.20s", user_id, endpoint)
        return sub

    async def delete_for_user(self, *, user_id, endpoint: str) -> int:
        logger.info("push subscription removed: user_id=%s endpoint=%.20s", user_id, endpoint)
        result = await self.db.execute(
            delete(PushSubscription)
            .where(PushSubscription.user_id == user_id)
            .where(PushSubscription.endpoint == endpoint)
        )
        await self.db.commit()
        return result.rowcount or 0

    async def delete_by_endpoint(self, endpoint: str) -> int:
        """Used when the push service tells us an endpoint is gone."""
        logger.info("push subscription deleted by endpoint: endpoint=%.20s", endpoint)
        result = await self.db.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        await self.db.commit()
        return result.rowcount or 0

    async def list_for_user(self, user_id) -> List[PushSubscription]:
        result = await self.db.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        return list(result.scalars().all())

    async def mark_success(self, subscription_id: int) -> None:
        logger.debug("push subscription marked success: id=%s", subscription_id)
        await self.db.execute(
            update(PushSubscription)
            .where(PushSubscription.id == subscription_id)
            .values(last_success_at=datetime.utcnow())
        )
        await self.db.commit()

    async def mark_failure(self, subscription_id: int) -> None:
        logger.warning("push subscription marked failure: id=%s", subscription_id)
        await self.db.execute(
            update(PushSubscription)
            .where(PushSubscription.id == subscription_id)
            .values(last_failure_at=datetime.utcnow())
        )
        await self.db.commit()