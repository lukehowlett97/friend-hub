import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.repository import (
    IMPORTED_IDENTITY_STATUSES,
    USER_STATUSES,
    USER_TYPES,
    IdentityRepository,
    normalise_identity_name,
)
from app.domains.identity.schemas import ImportedIdentityCreate, ImportedIdentityUpdate, UserCleanupUpdate
from app.models.imported_identity import ImportedIdentity
from app.models.message import User


class IdentityService:
    def __init__(self, db: AsyncSession):
        self.repository = IdentityRepository(db)

    async def list_imported_identities(self, **filters) -> list[ImportedIdentity]:
        return await self.repository.list_imported_identities(**filters)

    async def create_imported_identity(self, request: ImportedIdentityCreate) -> tuple[ImportedIdentity | None, str | None]:
        status = request.status or "unlinked"
        if status not in IMPORTED_IDENTITY_STATUSES:
            return None, "Invalid imported identity status"
        display_name = request.source_display_name.strip()
        if not display_name:
            return None, "Source display name is required"
        normalised_name = normalise_identity_name(request.normalised_name or display_name)
        identity = await self.repository.create_imported_identity(
            source=(request.source or "messenger").strip() or "messenger",
            source_participant_id=request.source_participant_id,
            source_display_name=display_name,
            normalised_name=normalised_name,
            status=status,
            message_count=max(0, request.message_count or 0),
            first_seen_at=request.first_seen_at,
            last_seen_at=request.last_seen_at,
            confidence_score=request.confidence_score,
            notes=request.notes,
        )
        return identity, None

    async def update_imported_identity(
        self,
        identity_id: uuid.UUID,
        request: ImportedIdentityUpdate,
    ) -> tuple[ImportedIdentity | None, str | None]:
        identity = await self.repository.get_imported_identity(identity_id)
        if not identity:
            return None, "Imported identity not found"

        updates = request.model_dump(exclude_unset=True)
        if "status" in updates and updates["status"] not in IMPORTED_IDENTITY_STATUSES:
            return None, "Invalid imported identity status"
        if "linked_user_id" in updates and updates["linked_user_id"] is not None:
            user = await self.repository.get_user(updates["linked_user_id"])
            if not user:
                return None, "Linked user not found"
            if not self._can_link_user(user):
                return None, "Linked user must be an active human account"
            updates["status"] = "linked"
            await self.repository.upsert_external_identity_mapping(identity, user)
            await self.repository.backfill_imported_message_identity(identity)
        if "linked_user_id" in updates and updates["linked_user_id"] is None and request.linked_user_id is None:
            updates["status"] = "unlinked" if identity.status == "linked" else identity.status
            await self.repository.clear_external_identity_mapping(identity)

        return await self.repository.update_imported_identity(identity, **updates), None

    async def link_imported_identity(self, identity_id: uuid.UUID, user_id: uuid.UUID) -> tuple[ImportedIdentity | None, str | None]:
        return await self.update_imported_identity(
            identity_id,
            ImportedIdentityUpdate(linked_user_id=user_id, status="linked"),
        )

    async def unlink_imported_identity(self, identity_id: uuid.UUID) -> tuple[ImportedIdentity | None, str | None]:
        identity = await self.repository.get_imported_identity(identity_id)
        if not identity:
            return None, "Imported identity not found"
        await self.repository.clear_external_identity_mapping(identity)
        return await self.repository.update_imported_identity(
            identity,
            linked_user_id=None,
            status="unlinked" if identity.status == "linked" else identity.status,
        ), None

    async def list_users_for_cleanup(self, **filters) -> list[dict]:
        return await self.repository.list_users_for_cleanup(**filters)

    async def update_user_cleanup(self, user_id: uuid.UUID, request: UserCleanupUpdate) -> tuple[User | None, str | None]:
        user = await self.repository.get_user(user_id)
        if not user:
            return None, "User not found"
        updates = request.model_dump(exclude_unset=True)
        if "user_type" in updates and updates["user_type"] not in USER_TYPES:
            return None, "Invalid user type"
        if "status" in updates and updates["status"] not in USER_STATUSES:
            return None, "Invalid user status"
        return await self.repository.update_user_cleanup(user, **updates), None

    @staticmethod
    def _can_link_user(user: User) -> bool:
        if not getattr(user, "is_active", False):
            return False
        if getattr(user, "is_test_user", False):
            return False
        if getattr(user, "user_type", "human") in {"system", "test"}:
            return False
        if getattr(user, "status", "active") in {"deactivated", "archived", "deleted"}:
            return False
        return True
