from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import MemberRole
from app.domains.permissions import can_assign_role

from .profile import (
    DEFAULT_NICKNAME_POLICY,
    NicknameChangePolicy,
    ProfileError,
    ProfileRepository,
    ProfileUpdate,
    can_edit_profile,
    normalize_update,
    serialize_profile,
)
from .repository import MemberRepository


class MemberService:
    def __init__(self, db: AsyncSession):
        self.repository = MemberRepository(db)
        self.profile_repository = ProfileRepository(db)

    async def get_members(self, include_bots: bool = False, room_id=None) -> List[dict]:
        return await self.repository.get_all_with_stats(include_bots=include_bots, room_id=room_id)

    async def get_unlinked_imported_members(self, room_id=None) -> List[dict]:
        return await self.repository.get_unlinked_imported_members(room_id=room_id)

    async def get_role(self, session_id: str) -> MemberRole:
        return await self.repository.get_role(session_id)

    async def can_manage_roles(self, session_id: str) -> bool:
        role = await self.get_role(session_id)
        return role in {MemberRole.owner, MemberRole.admin}

    async def assign_role(
        self,
        target_identifier: str,
        role: str,
        requester_session_id: str,
    ) -> bool:
        if role not in {item.value for item in MemberRole}:
            return False

        requester_role = await self.get_role(requester_session_id)
        target = await self.repository.get_member(target_identifier)
        if not target:
            return False
        target_role = target["role"]
        requested_role = MemberRole(role)

        if not can_assign_role(requester_role, target_role, requested_role):
            return False

        if target_role == MemberRole.owner and requested_role != MemberRole.owner:
            if await self.repository.count_owners() <= 1:
                return False

        return await self.repository.update_role(target_identifier, requested_role)

    async def get_profile(self, session_id: str) -> Optional[dict]:
        user = await self.profile_repository.get_by_session_id(session_id)
        if not user:
            return None
        return serialize_profile(user)

    async def update_profile(
        self,
        *,
        target_session_id: str,
        update_in: ProfileUpdate,
        requester_session_id: str,
        policy: NicknameChangePolicy = DEFAULT_NICKNAME_POLICY,
    ) -> dict:
        if update_in.is_empty():
            raise ProfileError("No profile fields supplied", status_code=400)

        target = await self.profile_repository.get_by_session_id(target_session_id)
        if not target:
            raise ProfileError("Member not found", status_code=404)

        requester_role = await self.get_role(requester_session_id)

        # Each field is gated separately so the per-field policy can diverge
        # later (Phase 2 makes nickname vote-required while display_role/bio
        # stay self-edit).
        for field in ("nickname", "display_role", "bio", "avatar_emoji"):
            if getattr(update_in, field) is None:
                continue
            allowed = can_edit_profile(
                requester_session_id=requester_session_id,
                requester_role=requester_role,
                target_session_id=target_session_id,
                policy=policy,
                field=field,
            )
            if not allowed:
                raise ProfileError(
                    f"Not permitted to change {field}", status_code=403
                )

        values = normalize_update(update_in)

        if "nickname" in values and values["nickname"] != target.nickname:
            from sqlalchemy import select, func
            from app.models.message import User

            existing = await self.profile_repository.db.execute(
                select(User.session_id)
                .where(func.lower(User.nickname) == values["nickname"].lower())
                .where(User.session_id != target.session_id)
            )
            if existing.scalar_one_or_none() is not None:
                raise ProfileError("Nickname is already taken", status_code=409)

        from datetime import datetime
        values["updated_at"] = datetime.utcnow()

        updated = await self.profile_repository.update_profile(target_session_id, values)
        return serialize_profile(updated) if updated else {}
