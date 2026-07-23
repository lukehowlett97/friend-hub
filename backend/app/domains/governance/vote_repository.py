from __future__ import annotations

from datetime import datetime
from typing import Iterable

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_vote_action import ChatVoteAction, ChatVoteStatus
from app.models.chat_vote_ballot import ChatVoteBallot
from app.models.member import GroupMember
from app.models.message import Message, User
from app.models.planning import DEFAULT_GROUP_SLUG, Group


BOT_USER_SESSION_ID = "00000000-0000-0000-0000-000000000b07"
BOT_NICKNAME = "Hub Bot"


class VoteRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def default_group(self) -> Group:
        result = await self.db.execute(select(Group).where(Group.slug == DEFAULT_GROUP_SLUG))
        group = result.scalar_one_or_none()
        if group:
            return group
        group = Group(name="Friend Hub", slug=DEFAULT_GROUP_SLUG)
        self.db.add(group)
        await self.db.flush()
        return group

    def _active_member_filter(self, group_id: int):
        return (
            User.is_active.is_(True),
            User.hidden_from_member_list.is_(False),
            User.is_test_user.is_(False),
            User.is_bot.is_(False),
            User.status.notin_(["deactivated", "archived", "deleted"]),
            User.user_type.notin_(["test", "system", "bot"]),
            GroupMember.group_id == group_id,
        )

    async def get_active_member_by_session_id(self, group_id: int, session_id: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .join(GroupMember, User.session_id == GroupMember.user_session_id)
            .where(User.session_id == session_id, *self._active_member_filter(group_id))
        )
        return result.scalar_one_or_none()

    async def count_active_members(self, group_id: int) -> int:
        result = await self.db.execute(
            select(func.count(func.distinct(User.id)))
            .join(GroupMember, User.session_id == GroupMember.user_session_id)
            .where(*self._active_member_filter(group_id))
        )
        return int(result.scalar_one() or 0)

    async def create_action(self, action: ChatVoteAction) -> ChatVoteAction:
        self.db.add(action)
        await self.db.flush()
        return action

    async def post_bot_message(self, content: str) -> Message:
        bot_uuid = uuid.UUID(BOT_USER_SESSION_ID)
        message = Message(
            user_session_id=bot_uuid,
            user_id=bot_uuid,
            content=content[:2000],
            created_at=datetime.utcnow(),
        )
        self.db.add(message)
        await self.db.flush()
        return message

    async def set_open_message_id(self, action: ChatVoteAction, message_id: int) -> None:
        action.open_message_id = message_id
        action.updated_at = datetime.utcnow()
        await self.db.flush()

    async def get_action(self, vote_action_id: int) -> ChatVoteAction | None:
        return await self.db.get(ChatVoteAction, vote_action_id)

    async def list_actions(self, group_id: int, *, statuses: Iterable[str] | None = None) -> list[ChatVoteAction]:
        stmt = select(ChatVoteAction).where(ChatVoteAction.group_id == group_id)
        if statuses:
            stmt = stmt.where(ChatVoteAction.status.in_(list(statuses)))
        stmt = stmt.order_by(ChatVoteAction.created_at.desc(), ChatVoteAction.id.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_ballot(self, vote_action_id: int, user_id) -> ChatVoteBallot | None:
        result = await self.db.execute(
            select(ChatVoteBallot).where(
                ChatVoteBallot.vote_action_id == vote_action_id,
                ChatVoteBallot.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert_ballot(self, vote_action_id: int, user_id, vote: str) -> ChatVoteBallot:
        ballot = await self.get_ballot(vote_action_id, user_id)
        now = datetime.utcnow()
        if ballot:
            ballot.vote = vote
            ballot.updated_at = now
            await self.db.flush()
            return ballot
        ballot = ChatVoteBallot(vote_action_id=vote_action_id, user_id=user_id, vote=vote)
        self.db.add(ballot)
        await self.db.flush()
        return ballot

    async def recalculate_counts(self, action: ChatVoteAction) -> tuple[int, int]:
        result = await self.db.execute(
            select(
                func.count(ChatVoteBallot.id).filter(ChatVoteBallot.vote == "yes"),
                func.count(ChatVoteBallot.id).filter(ChatVoteBallot.vote == "no"),
            ).where(ChatVoteBallot.vote_action_id == action.id)
        )
        yes_count, no_count = result.one()
        action.yes_count = int(yes_count or 0)
        action.no_count = int(no_count or 0)
        action.updated_at = datetime.utcnow()
        await self.db.flush()
        return action.yes_count, action.no_count

    async def get_user_votes(self, vote_action_ids: list[int], user_id) -> dict[int, str]:
        if not vote_action_ids or user_id is None:
            return {}
        result = await self.db.execute(
            select(ChatVoteBallot.vote_action_id, ChatVoteBallot.vote)
            .where(ChatVoteBallot.vote_action_id.in_(vote_action_ids), ChatVoteBallot.user_id == user_id)
        )
        return {int(vote_action_id): vote for vote_action_id, vote in result.fetchall()}

    async def users_by_id(self, user_ids: list) -> dict[str, User]:
        ids = [user_id for user_id in user_ids if user_id]
        if not ids:
            return {}
        result = await self.db.execute(select(User).where(User.id.in_(ids)))
        users = result.scalars().all()
        return {str(user.id): user for user in users}

    async def set_action_status(
        self,
        action: ChatVoteAction,
        *,
        status: str,
        resolved_by_user_id=None,
    ) -> ChatVoteAction:
        action.status = status
        action.resolved_at = datetime.utcnow()
        action.updated_at = action.resolved_at
        action.resolved_by_user_id = resolved_by_user_id
        await self.db.flush()
        return action

    async def set_result_message_id(self, action: ChatVoteAction, message_id: int) -> None:
        action.result_message_id = message_id
        action.updated_at = datetime.utcnow()
        await self.db.flush()

    async def update_target_nickname(self, target_user_id, nickname: str) -> None:
        await self.db.execute(
            update(User)
            .where(User.id == target_user_id)
            .values(nickname=nickname, updated_at=datetime.utcnow())
        )
        await self.db.flush()

    async def update_target_display_role(self, target_user_id, display_role: str) -> None:
        await self.db.execute(
            update(User)
            .where(User.id == target_user_id)
            .values(display_role=display_role, updated_at=datetime.utcnow())
        )
        await self.db.flush()

    async def open_expired_actions(self, now: datetime) -> list[ChatVoteAction]:
        result = await self.db.execute(
            select(ChatVoteAction)
            .where(ChatVoteAction.status == ChatVoteStatus.open.value, ChatVoteAction.expires_at <= now)
            .order_by(ChatVoteAction.expires_at.asc(), ChatVoteAction.id.asc())
        )
        return list(result.scalars().all())
