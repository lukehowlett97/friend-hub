"""
Reaction repository — toggle and batch-fetch emoji reactions.
"""
import logging
from typing import Dict, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reaction import Reaction
from app.models.message import User

logger = logging.getLogger(__name__)


class ReactionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def toggle_reaction(
        self, message_id: int, session_id: str, emoji: str, user_id=None
    ) -> List[dict]:
        """
        Add, update, or remove a reaction.
        - same emoji again  → removes it (toggle off)
        - different emoji   → replaces the old one
        - no prior reaction → adds it
        Returns the updated reaction list for the message.
        """
        result = await self.db.execute(
            select(Reaction).where(
                Reaction.message_id == message_id,
                Reaction.user_session_id == session_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            if existing.emoji == emoji:
                await self.db.delete(existing)
            else:
                existing.emoji = emoji
                if user_id is not None:
                    existing.user_id = user_id
        else:
            self.db.add(Reaction(
                message_id=message_id,
                user_session_id=session_id,
                user_id=user_id,
                emoji=emoji,
            ))

        await self.db.commit()
        reactions_map = await self.get_reactions_for_messages([message_id])
        return reactions_map.get(message_id, [])

    async def get_reactions_for_messages(self, message_ids: List[int]) -> Dict[int, List[dict]]:
        """
        Batch-fetch reactions for a list of message IDs.
        Returns {message_id: [{emoji, count, session_ids, nicknames}]}.
        Nicknames allow the frontend to show "Alice, Bob reacted" on hover.
        """
        if not message_ids:
            return {}

        result = await self.db.execute(
            select(Reaction, User.nickname)
            .outerjoin(User, Reaction.user_session_id == User.session_id)
            .where(Reaction.message_id.in_(message_ids))
        )
        rows = result.all()

        # Group: message_id → emoji → [(session_id, nickname)]
        grouped: Dict[int, Dict[str, List[tuple]]] = {}
        for reaction, nickname in rows:
            mid = reaction.message_id
            grouped.setdefault(mid, {}).setdefault(reaction.emoji, []).append(
                (str(reaction.user_session_id), nickname or "Unknown")
            )

        return {
            mid: [
                {
                    "emoji": emoji,
                    "count": len(reactors),
                    "session_ids": [r[0] for r in reactors],
                    "nicknames": [r[1] for r in reactors],
                }
                for emoji, reactors in emoji_map.items()
            ]
            for mid, emoji_map in grouped.items()
        }
