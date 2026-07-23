from datetime import datetime
import uuid

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.identity.detection import detect_user_cleanup_candidate
from app.models.import_tracking import ExternalIdentity, ImportedMessageSource
from app.models.imported_identity import ImportedIdentity
from app.models.message import Message, User


IMPORTED_IDENTITY_STATUSES = {"unlinked", "linked", "ignored", "duplicate", "archived"}
USER_TYPES = {"human", "bot", "system", "test"}
USER_STATUSES = {"active", "invited", "deactivated", "archived", "deleted"}


def normalise_identity_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


class IdentityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_imported_identities(
        self,
        *,
        status: str | None = None,
        source: str | None = None,
        search: str | None = None,
        linked_user_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ImportedIdentity]:
        query = select(ImportedIdentity).order_by(ImportedIdentity.source_display_name.asc())
        filters = []
        if status:
            filters.append(ImportedIdentity.status == status)
        if source:
            filters.append(ImportedIdentity.source == source)
        if linked_user_id:
            filters.append(ImportedIdentity.linked_user_id == linked_user_id)
        if search:
            needle = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(ImportedIdentity.source_display_name).like(needle),
                    func.lower(ImportedIdentity.normalised_name).like(needle),
                    func.lower(ImportedIdentity.notes).like(needle),
                )
            )
        if filters:
            query = query.where(and_(*filters))
        result = await self.db.execute(query.limit(max(1, min(limit, 500))).offset(max(0, offset)))
        return list(result.scalars().all())

    async def create_imported_identity(self, **values) -> ImportedIdentity:
        identity = ImportedIdentity(**values)
        self.db.add(identity)
        await self.db.commit()
        await self.db.refresh(identity)
        return identity

    async def get_imported_identity(self, identity_id: uuid.UUID) -> ImportedIdentity | None:
        result = await self.db.execute(select(ImportedIdentity).where(ImportedIdentity.id == identity_id))
        return result.scalar_one_or_none()

    async def get_user(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def upsert_external_identity_mapping(self, identity: ImportedIdentity, user: User) -> None:
        result = await self.db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == identity.source,
                ExternalIdentity.external_name == identity.source_display_name,
            )
        )
        external_identity = result.scalar_one_or_none()
        if external_identity is None:
            self.db.add(ExternalIdentity(
                provider=identity.source,
                external_name=identity.source_display_name,
                user_id=user.id,
                user_session_id=user.session_id,
            ))
        else:
            external_identity.user_id = user.id
            external_identity.user_session_id = user.session_id
            external_identity.updated_at = datetime.utcnow()

    async def backfill_imported_message_identity(self, identity: ImportedIdentity) -> int:
        source_message_ids = (
            select(ImportedMessageSource.message_id)
            .where(
                ImportedMessageSource.provider == identity.source,
                ImportedMessageSource.raw_sender_name == identity.source_display_name,
            )
        )
        result = await self.db.execute(
            update(Message)
            .where(Message.id.in_(source_message_ids))
            .values(imported_identity_id=identity.id)
        )
        return result.rowcount or 0

    async def clear_external_identity_mapping(self, identity: ImportedIdentity) -> None:
        result = await self.db.execute(
            select(ExternalIdentity).where(
                ExternalIdentity.provider == identity.source,
                ExternalIdentity.external_name == identity.source_display_name,
            )
        )
        external_identity = result.scalar_one_or_none()
        if external_identity is not None:
            external_identity.user_id = None
            external_identity.user_session_id = None
            external_identity.updated_at = datetime.utcnow()

    async def update_imported_identity(self, identity: ImportedIdentity, **updates) -> ImportedIdentity:
        for key, value in updates.items():
            setattr(identity, key, value)
        identity.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(identity)
        return identity

    async def list_users_for_cleanup(
        self,
        *,
        status: str | None = None,
        user_type: str | None = None,
        search: str | None = None,
        likely_test_user: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        message_join = or_(
            Message.user_id == User.id,
            and_(Message.user_id.is_(None), Message.user_session_id == User.session_id),
        )
        query = (
            select(User, func.count(Message.id).label("message_count"))
            .outerjoin(Message, message_join)
            .group_by(User.session_id)
            .order_by(User.created_at.desc())
        )
        filters = []
        if status:
            filters.append(User.status == status)
        if user_type:
            filters.append(User.user_type == user_type)
        if search:
            needle = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(User.username).like(needle),
                    func.lower(User.nickname).like(needle),
                    func.lower(User.display_name).like(needle),
                )
            )
        if filters:
            query = query.where(and_(*filters))
        result = await self.db.execute(query.limit(max(1, min(limit, 500))).offset(max(0, offset)))

        users = []
        for user, message_count in result.fetchall():
            suggestion = detect_user_cleanup_candidate(user, message_count or 0)
            if likely_test_user is not None and suggestion.likely_test_user != likely_test_user:
                continue
            users.append({"user": user, "message_count": message_count or 0, "suggestion": suggestion})
        return users

    async def update_user_cleanup(self, user: User, **updates) -> User:
        for key, value in updates.items():
            setattr(user, key, value)

        if "status" in updates:
            if user.status in {"deactivated", "archived", "deleted"}:
                user.is_active = False
                user.deactivated_at = user.deactivated_at or datetime.utcnow()
            elif user.status == "active":
                user.is_active = True
                user.deactivated_at = None

        if "user_type" in updates:
            user.is_bot = user.is_bot or user.user_type == "bot"
            user.is_test_user = user.is_test_user or user.user_type == "test"

        user.updated_at = datetime.utcnow()
        await self.db.commit()
        await self.db.refresh(user)
        return user
