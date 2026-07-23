from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.domains.members.profile import (
    DEFAULT_NICKNAME_POLICY,
    NicknameChangePolicy,
    ProfileError,
    validate_display_role,
    validate_nickname,
)
from app.models.chat_vote_action import (
    ChatVoteAction,
    ChatVoteActionType,
    ChatVoteStatus,
    ChatVoteThresholdType,
)
from app.models.member import MemberRole
from app.models.message import User

from .vote_repository import VoteRepository


class VoteError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _role_value(user: User) -> str:
    role = getattr(user, "role", None)
    return role.value if hasattr(role, "value") else (role or "member")


def _is_admin_user(user: User) -> bool:
    return _role_value(user) in {"owner", "admin"}


class VoteService:
    DEFAULT_DURATION = timedelta(minutes=10)

    def __init__(self, repository: VoteRepository, *, enable_chat_messages: bool = False):
        self.repository = repository
        self.enable_chat_messages = enable_chat_messages

    async def create_nickname_vote(
        self,
        *,
        proposer: User,
        target_session_id: str,
        proposed_nickname: str,
        reason: str | None = None,
        expires_at: datetime | None = None,
        policy: NicknameChangePolicy = DEFAULT_NICKNAME_POLICY,
    ) -> dict:
        group = await self.repository.default_group()
        proposer_member = await self.repository.get_active_member_by_session_id(group.id, str(proposer.session_id))
        if not proposer_member:
            raise VoteError("Proposer is not an active group member", status_code=403)

        target = await self.repository.get_active_member_by_session_id(group.id, target_session_id)
        if not target:
            raise VoteError("Target member not found", status_code=404)

        try:
            cleaned_nickname = validate_nickname(proposed_nickname)
        except ProfileError as exc:
            raise VoteError(exc.message, status_code=exc.status_code)

        self._validate_policy(proposer_member, target, policy)

        active_count = await self.repository.count_active_members(group.id)
        if active_count <= 0:
            raise VoteError("No active members available to vote", status_code=400)
        threshold_value = (active_count // 2) + 1

        now = datetime.utcnow()
        expires = expires_at or (now + self.DEFAULT_DURATION)
        if expires <= now:
            raise VoteError("expires_at must be in the future", status_code=400)

        payload = {
            "target_session_id": str(target.session_id),
            "current_nickname": target.nickname,
            "proposed_nickname": cleaned_nickname,
        }
        if reason and reason.strip():
            payload["reason"] = reason.strip()[:500]

        title = f"Rename {target.nickname} to \"{cleaned_nickname}\""
        summary = f"{proposer_member.nickname} proposed renaming {target.nickname} to \"{cleaned_nickname}\"."
        action = ChatVoteAction(
            group_id=group.id,
            created_by_user_id=proposer_member.id,
            target_user_id=target.id,
            action_type=ChatVoteActionType.nickname_change.value,
            status=ChatVoteStatus.open.value,
            title=title[:160],
            summary=summary,
            payload_json=payload,
            threshold_type=ChatVoteThresholdType.active_member_majority.value,
            threshold_value=threshold_value,
            expires_at=expires,
            created_at=now,
            updated_at=now,
        )
        await self.repository.create_action(action)
        await self._ensure_open_message(action)
        await self.repository.db.commit()
        return await self.serialize_action(action, current_user_id=proposer_member.id)

    async def create_display_role_vote(
        self,
        *,
        proposer: User,
        target_session_id: str,
        proposed_display_role: str,
        reason: str | None = None,
        expires_at: datetime | None = None,
    ) -> dict:
        group = await self.repository.default_group()
        proposer_member = await self.repository.get_active_member_by_session_id(group.id, str(proposer.session_id))
        if not proposer_member:
            raise VoteError("Proposer is not an active group member", status_code=403)

        target = await self.repository.get_active_member_by_session_id(group.id, target_session_id)
        if not target:
            raise VoteError("Target member not found", status_code=404)

        try:
            cleaned_role = validate_display_role(proposed_display_role)
        except ProfileError as exc:
            raise VoteError(exc.message, status_code=exc.status_code)

        active_count = await self.repository.count_active_members(group.id)
        if active_count <= 0:
            raise VoteError("No active members available to vote", status_code=400)
        threshold_value = (active_count // 2) + 1

        now = datetime.utcnow()
        expires = expires_at or (now + self.DEFAULT_DURATION)
        if expires <= now:
            raise VoteError("expires_at must be in the future", status_code=400)

        current_role = getattr(target, "display_role", None) or "Citizen"
        payload = {
            "target_session_id": str(target.session_id),
            "target_nickname": target.nickname,
            "current_display_role": current_role,
            "proposed_display_role": cleaned_role,
        }
        if reason and reason.strip():
            payload["reason"] = reason.strip()[:500]

        title = f"Make {target.nickname} \"{cleaned_role}\""
        summary = f"{proposer_member.nickname} proposed making {target.nickname} \"{cleaned_role}\"."
        action = ChatVoteAction(
            group_id=group.id,
            created_by_user_id=proposer_member.id,
            target_user_id=target.id,
            action_type=ChatVoteActionType.display_role_change.value,
            status=ChatVoteStatus.open.value,
            title=title[:160],
            summary=summary,
            payload_json=payload,
            threshold_type=ChatVoteThresholdType.active_member_majority.value,
            threshold_value=threshold_value,
            expires_at=expires,
            created_at=now,
            updated_at=now,
        )
        await self.repository.create_action(action)
        await self._ensure_open_message(action)
        await self.repository.db.commit()
        return await self.serialize_action(action, current_user_id=proposer_member.id)

    def _validate_policy(self, proposer: User, target: User, policy: NicknameChangePolicy) -> None:
        if _is_admin_user(proposer):
            return
        if policy == NicknameChangePolicy.admin_only:
            raise VoteError("Nickname votes are not allowed by current policy", status_code=403)
        if policy in {NicknameChangePolicy.vote_required, NicknameChangePolicy.free_for_all}:
            return
        if policy == NicknameChangePolicy.self_edit:
            if proposer.session_id == target.session_id:
                raise VoteError("Self nickname changes can be edited directly", status_code=400)
            return

    async def cast_vote(self, *, vote_action_id: int, voter: User, vote: str) -> dict:
        normalized_vote = (vote or "").strip().lower()
        if normalized_vote not in {"yes", "no"}:
            raise VoteError("vote must be yes or no", status_code=400)

        action = await self.repository.get_action(vote_action_id)
        if not action:
            raise VoteError("Vote action not found", status_code=404)

        group = await self.repository.default_group()
        if action.group_id != group.id:
            raise VoteError("Vote action not found", status_code=404)

        voter_member = await self.repository.get_active_member_by_session_id(group.id, str(voter.session_id))
        if not voter_member:
            raise VoteError("Only active group members can vote", status_code=403)

        now = datetime.utcnow()
        if action.status != ChatVoteStatus.open.value:
            raise VoteError("Vote action is not open", status_code=400)
        if action.expires_at <= now:
            await self._expire_action(action)
            await self.repository.db.commit()
            raise VoteError("Vote action has expired", status_code=400)

        await self.repository.upsert_ballot(action.id, voter_member.id, normalized_vote)
        await self.repository.recalculate_counts(action)
        resolved = False
        if action.yes_count >= action.threshold_value:
            await self._pass_action(action, resolved_by_user_id=voter_member.id)
            resolved = True
        await self.repository.db.commit()
        return {
            "vote_action": await self.serialize_action(action, current_user_id=voter_member.id),
            "resolved": resolved,
        }

    async def cancel_vote(self, *, vote_action_id: int, actor: User) -> dict:
        action = await self.repository.get_action(vote_action_id)
        if not action:
            raise VoteError("Vote action not found", status_code=404)
        if action.status != ChatVoteStatus.open.value:
            raise VoteError("Only open vote actions can be cancelled", status_code=400)
        if not _is_admin_user(actor) and str(action.created_by_user_id) != str(actor.id):
            raise VoteError("Only the proposer or an admin can cancel this vote", status_code=403)
        await self.repository.set_action_status(
            action,
            status=ChatVoteStatus.cancelled.value,
            resolved_by_user_id=actor.id,
        )
        await self._ensure_result_message(action)
        await self.repository.db.commit()
        return {"vote_action": await self.serialize_action(action, current_user_id=actor.id), "resolved": True}

    async def resolve_vote(self, *, vote_action_id: int, actor: User | None = None) -> dict:
        action = await self.repository.get_action(vote_action_id)
        if not action:
            raise VoteError("Vote action not found", status_code=404)
        if action.status != ChatVoteStatus.open.value:
            return {
                "vote_action": await self.serialize_action(action, current_user_id=getattr(actor, "id", None)),
                "resolved": False,
            }
        await self.repository.recalculate_counts(action)
        if action.yes_count >= action.threshold_value:
            await self._pass_action(action, resolved_by_user_id=getattr(actor, "id", None))
            resolved = True
        elif action.expires_at <= datetime.utcnow():
            await self._expire_action(action, resolved_by_user_id=getattr(actor, "id", None))
            resolved = True
        else:
            resolved = False
        await self.repository.db.commit()
        return {
            "vote_action": await self.serialize_action(action, current_user_id=getattr(actor, "id", None)),
            "resolved": resolved,
        }

    async def expire_votes(self, *, now: datetime | None = None) -> list[dict]:
        now = now or datetime.utcnow()
        actions = await self.repository.open_expired_actions(now)
        expired: list[dict] = []
        for action in actions:
            await self._expire_action(action)
            expired.append(await self.serialize_action(action))
        await self.repository.db.commit()
        return expired

    async def list_votes(self, *, current_user: User | None = None) -> list[dict]:
        group = await self.repository.default_group()
        actions = await self.repository.list_actions(group.id)
        current_user_id = current_user.id if current_user else None
        return [await self.serialize_action(action, current_user_id=current_user_id) for action in actions]

    async def get_vote(self, *, vote_action_id: int, current_user: User | None = None) -> dict:
        group = await self.repository.default_group()
        action = await self.repository.get_action(vote_action_id)
        if not action or action.group_id != group.id:
            raise VoteError("Vote action not found", status_code=404)
        return await self.serialize_action(action, current_user_id=current_user.id if current_user else None)

    async def _pass_action(self, action: ChatVoteAction, *, resolved_by_user_id=None) -> None:
        if action.action_type == ChatVoteActionType.nickname_change.value:
            proposed = (action.payload_json or {}).get("proposed_nickname")
            if not proposed:
                raise VoteError("Vote action is missing proposed nickname", status_code=500)
            await self.repository.update_target_nickname(action.target_user_id, proposed)
        elif action.action_type == ChatVoteActionType.display_role_change.value:
            proposed = (action.payload_json or {}).get("proposed_display_role")
            if not proposed:
                raise VoteError("Vote action is missing proposed display role", status_code=500)
            await self.repository.update_target_display_role(action.target_user_id, proposed)
        await self.repository.set_action_status(
            action,
            status=ChatVoteStatus.passed.value,
            resolved_by_user_id=resolved_by_user_id,
        )
        await self._ensure_result_message(action)

    async def _expire_action(self, action: ChatVoteAction, *, resolved_by_user_id=None) -> None:
        await self.repository.set_action_status(
            action,
            status=ChatVoteStatus.expired.value,
            resolved_by_user_id=resolved_by_user_id,
        )
        await self._ensure_result_message(action)

    async def _ensure_open_message(self, action: ChatVoteAction) -> None:
        if not self.enable_chat_messages or action.open_message_id:
            return
        if not hasattr(self.repository, "post_bot_message"):
            return
        content = f"{action.summary or action.title}\n[[vote-action:{action.id}]]"
        message = await self.repository.post_bot_message(content)
        await self.repository.set_open_message_id(action, message.id)

    async def _ensure_result_message(self, action: ChatVoteAction) -> None:
        if not self.enable_chat_messages or action.result_message_id:
            return
        if not hasattr(self.repository, "post_bot_message"):
            return
        content = self._result_message_content(action)
        message = await self.repository.post_bot_message(content)
        await self.repository.set_result_message_id(action, message.id)

    def _result_message_content(self, action: ChatVoteAction) -> str:
        payload = action.payload_json or {}
        if action.action_type == ChatVoteActionType.display_role_change.value:
            current = payload.get("current_display_role") or "their current role"
            proposed = payload.get("proposed_display_role") or "the proposed role"
            target = self._target_label(action)
            if action.status == ChatVoteStatus.passed.value:
                return f"Motion passed. {target}'s chat role is now \"{proposed}\"."
            if action.status == ChatVoteStatus.cancelled.value:
                return f"Motion cancelled. {target} keeps their chat role: \"{current}\"."
            if action.status == ChatVoteStatus.expired.value:
                return f"Motion expired. {target} keeps their chat role: \"{current}\"."
            if action.status == ChatVoteStatus.failed.value:
                return f"Motion failed. {target} keeps their chat role: \"{current}\"."
            return f"Motion resolved. {target} keeps their chat role: \"{current}\"."

        current = payload.get("current_nickname") or "the member"
        proposed = payload.get("proposed_nickname") or "the proposed nickname"
        if action.status == ChatVoteStatus.passed.value:
            return f"Motion passed. {current} is now known as \"{proposed}\"."
        if action.status == ChatVoteStatus.cancelled.value:
            return f"Motion cancelled. {current} keeps their nickname."
        if action.status == ChatVoteStatus.expired.value:
            return f"Motion expired. {current} keeps their nickname."
        if action.status == ChatVoteStatus.failed.value:
            return f"Motion failed. {current} keeps their nickname."
        return f"Motion resolved. {current} keeps their nickname."

    def _target_label(self, action: ChatVoteAction) -> str:
        payload = action.payload_json or {}
        return payload.get("target_nickname") or "The member"

    async def serialize_action(self, action: ChatVoteAction, *, current_user_id=None) -> dict:
        users = await self.repository.users_by_id([action.created_by_user_id, action.target_user_id, action.resolved_by_user_id])
        proposer = users.get(str(action.created_by_user_id))
        target = users.get(str(action.target_user_id))
        resolved_by = users.get(str(action.resolved_by_user_id))
        current_vote = None
        if current_user_id is not None:
            current_vote = (await self.repository.get_user_votes([action.id], current_user_id)).get(action.id)
        return {
            "id": action.id,
            "group_id": action.group_id,
            "created_by_user_id": str(action.created_by_user_id) if action.created_by_user_id else None,
            "created_by": self._user_payload(proposer),
            "target_user_id": str(action.target_user_id) if action.target_user_id else None,
            "target_user": self._user_payload(target),
            "action_type": action.action_type,
            "status": action.status,
            "title": action.title,
            "summary": action.summary,
            "payload": action.payload_json or {},
            "threshold_type": action.threshold_type,
            "threshold_value": action.threshold_value,
            "yes_count": action.yes_count,
            "no_count": action.no_count,
            "expires_at": action.expires_at.isoformat() if action.expires_at else None,
            "resolved_at": action.resolved_at.isoformat() if action.resolved_at else None,
            "created_at": action.created_at.isoformat() if action.created_at else None,
            "updated_at": action.updated_at.isoformat() if action.updated_at else None,
            "resolved_by_user_id": str(action.resolved_by_user_id) if action.resolved_by_user_id else None,
            "resolved_by": self._user_payload(resolved_by),
            "open_message_id": action.open_message_id,
            "result_message_id": action.result_message_id,
            "current_user_vote": current_vote,
        }

    @staticmethod
    def _user_payload(user: User | None) -> dict[str, Any] | None:
        if not user:
            return None
        return {
            "id": str(user.id),
            "session_id": str(user.session_id),
            "username": user.username,
            "nickname": user.nickname,
            "role": _role_value(user),
            "display_role": getattr(user, "display_role", None),
            "avatar_url": getattr(user, "avatar_url", None),
        }
