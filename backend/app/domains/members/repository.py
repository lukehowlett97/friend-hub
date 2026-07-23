from datetime import datetime, timedelta
from typing import List

from sqlalchemy import and_, case, desc, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.member import GroupMember, MemberRole
from app.models.imported_identity import ImportedIdentity
from app.models.message import Message, User, UserRole


class MemberRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_with_stats(self, include_bots: bool = False, room_id=None) -> List[dict]:
        from app.models.room import RoomMembership

        cutoff_time = datetime.utcnow() - timedelta(minutes=30)

        last_seen_value = func.coalesce(User.last_seen_at, User.last_seen)
        online_value = case(
            (and_(User.is_active.is_(True), last_seen_value >= cutoff_time), True),
            else_=False,
        ).label("is_online")
        effective_message_user_id = case(
            (
                and_(
                    Message.is_imported.is_(True),
                    ImportedIdentity.linked_user_id.is_not(None),
                ),
                ImportedIdentity.linked_user_id,
            ),
            else_=User.id,
        )
        message_count_filters = [Message.is_deleted.is_(False)]
        if room_id is not None:
            message_count_filters.append(Message.room_id == room_id)
        message_counts = (
            select(
                effective_message_user_id.label("user_id"),
                func.count(Message.id).label("message_count"),
                func.count(Message.id)
                .filter(Message.is_imported.is_(True))
                .label("imported_message_count"),
            )
            .select_from(Message)
            .join(User, Message.user_session_id == User.session_id)
            .outerjoin(ImportedIdentity, Message.imported_identity_id == ImportedIdentity.id)
            .where(*message_count_filters)
            .group_by(effective_message_user_id)
            .subquery()
        )

        stmt = (
            select(
                User.id,
                User.session_id,
                User.username,
                User.nickname,
                User.avatar_url,
                User.avatar_emoji,
                User.display_role,
                User.bio,
                User.role.label("user_role"),
                User.user_type,
                User.status,
                User.is_test_user,
                User.is_bot,
                User.hidden_from_member_list,
                GroupMember.role.label("member_role"),
                online_value,
                func.coalesce(message_counts.c.message_count, 0).label("message_count"),
                func.coalesce(message_counts.c.imported_message_count, 0).label("imported_message_count"),
                User.joined_at,
                last_seen_value.label("last_seen"),
                User.last_login_at,
                User.pin_hash,
                User.invite_code_hash,
                User.invite_code_used_at,
                User.is_active.label("is_active"),
            )
            .outerjoin(GroupMember, User.session_id == GroupMember.user_session_id)
            .outerjoin(message_counts, message_counts.c.user_id == User.id)
            .where(
                User.is_active.is_(True),
                or_(User.hidden_from_member_list.is_(False), and_(include_bots, User.username == "hub_bot")),
                User.is_test_user.is_(False),
                or_(User.is_bot.is_(False), and_(include_bots, User.username == "hub_bot")),
                User.status.notin_(["deactivated", "archived", "deleted"]),
                or_(User.user_type.notin_(["test", "system", "bot"]), and_(include_bots, User.username == "hub_bot")),
            )
        )

        if room_id is not None:
            native_message_exists = (
                select(Message.id)
                .where(
                    Message.room_id == room_id,
                    Message.is_deleted.is_(False),
                    Message.is_imported.is_(False),
                    or_(
                        Message.user_id == User.id,
                        and_(Message.user_id.is_(None), Message.user_session_id == User.session_id),
                    ),
                )
                .exists()
            )
            linked_import_exists = (
                select(Message.id)
                .select_from(Message)
                .join(ImportedIdentity, Message.imported_identity_id == ImportedIdentity.id)
                .where(
                    Message.room_id == room_id,
                    Message.is_deleted.is_(False),
                    Message.is_imported.is_(True),
                    Message.user_session_id == User.session_id,
                    ImportedIdentity.linked_user_id.is_not(None),
                    ImportedIdentity.linked_user_id != User.id,
                )
                .exists()
            )
            stmt = stmt.where(
                User.id.in_(
                    select(RoomMembership.user_id).where(RoomMembership.room_id == room_id)
                ),
                or_(native_message_exists, ~linked_import_exists),
            )

        result = await self.db.execute(
            stmt
            .group_by(
                User.id,
                User.session_id,
                User.username,
                User.nickname,
                User.avatar_url,
                User.avatar_emoji,
                User.display_role,
                User.bio,
                User.role,
                User.user_type,
                User.status,
                User.is_test_user,
                User.is_bot,
                User.hidden_from_member_list,
                GroupMember.role,
                User.joined_at,
                User.last_seen,
                User.last_seen_at,
                User.last_login_at,
                User.pin_hash,
                User.invite_code_hash,
                User.invite_code_used_at,
                message_counts.c.message_count,
                message_counts.c.imported_message_count,
            )
            .order_by(
                case(
                    (User.role == UserRole.owner, 0),
                    (GroupMember.role == MemberRole.owner, 0),
                    (User.role == UserRole.admin, 1),
                    (GroupMember.role == MemberRole.admin, 1),
                    else_=2,
                ),
                User.joined_at.desc(),
            )
        )

        return [
            {
                "id": str(row.id),
                "session_id": str(row.session_id),
                "username": row.username,
                "nickname": row.nickname,
                "avatar_url": row.avatar_url,
                "avatar_emoji": row.avatar_emoji,
                "display_role": row.display_role,
                "bio": row.bio,
                "role": self._response_role(row.user_role, row.member_role).value,
                "is_online": bool(row.is_online),
                "is_imported": row.username is None and not bool(row.is_active),
                "user_type": row.user_type,
                "status": row.status,
                "is_test_user": bool(row.is_test_user),
                "is_bot": bool(row.is_bot),
                "hidden_from_member_list": bool(row.hidden_from_member_list),
                "message_count": row.message_count or 0,
                "imported_message_count": row.imported_message_count or 0,
                "joined_at": row.joined_at.isoformat() if row.joined_at else None,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                "last_login_at": row.last_login_at.isoformat() if row.last_login_at else None,
                "has_pin": bool(row.pin_hash),
                "invite_pending": bool(row.invite_code_hash and not row.invite_code_used_at),
            }
            for row in result.fetchall()
        ]

    async def get_unlinked_imported_members(self, room_id=None) -> List[dict]:
        LinkedUser = User.__table__.alias("linked_user")
        filters = [
            Message.is_deleted.is_(False),
            Message.is_imported.is_(True),
            or_(
                ImportedIdentity.linked_user_id.is_(None),
                LinkedUser.c.username.ilike("legacy_%"),
            ),
        ]
        if room_id is not None:
            filters.append(Message.room_id == room_id)

        result = await self.db.execute(
            select(
                ImportedIdentity.id,
                ImportedIdentity.source_display_name,
                ImportedIdentity.normalised_name,
                ImportedIdentity.status,
                ImportedIdentity.first_seen_at,
                ImportedIdentity.last_seen_at,
                LinkedUser.c.username.label("linked_username"),
                LinkedUser.c.nickname.label("linked_nickname"),
                func.count(Message.id).label("message_count"),
            )
            .select_from(ImportedIdentity)
            .join(Message, Message.imported_identity_id == ImportedIdentity.id)
            .outerjoin(LinkedUser, ImportedIdentity.linked_user_id == LinkedUser.c.id)
            .where(*filters)
            .group_by(
                ImportedIdentity.id,
                ImportedIdentity.source_display_name,
                ImportedIdentity.normalised_name,
                ImportedIdentity.status,
                ImportedIdentity.first_seen_at,
                ImportedIdentity.last_seen_at,
                LinkedUser.c.username,
                LinkedUser.c.nickname,
            )
            .order_by(desc("message_count"), ImportedIdentity.source_display_name.asc())
        )

        return [
            {
                "id": str(row.id),
                "nickname": row.source_display_name,
                "normalised_name": row.normalised_name,
                "status": row.status,
                "linked_username": row.linked_username,
                "linked_nickname": row.linked_nickname,
                "message_count": row.message_count or 0,
                "first_seen_at": row.first_seen_at.isoformat() if row.first_seen_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            }
            for row in result.fetchall()
        ]

    async def get_member(self, identifier: str) -> dict | None:
        result = await self.db.execute(
            select(
                User.id,
                User.session_id,
                User.role.label("user_role"),
                GroupMember.role.label("member_role"),
            )
            .outerjoin(GroupMember, User.session_id == GroupMember.user_session_id)
            .where(or_(User.session_id == identifier, User.id == identifier))
        )
        row = result.first()
        if not row:
            return None
        return {
            "id": row.id,
            "session_id": row.session_id,
            "role": self._response_role(row.user_role, row.member_role),
        }

    async def get_role(self, identifier: str) -> MemberRole:
        member = await self.get_member(identifier)
        if member:
            return member["role"]

        result = await self.db.execute(
            select(GroupMember.role).where(GroupMember.user_session_id == identifier)
        )
        return result.scalar_one_or_none() or MemberRole.member

    async def count_owners(self) -> int:
        result = await self.db.execute(
            select(func.count(func.distinct(User.session_id)))
            .outerjoin(GroupMember, User.session_id == GroupMember.user_session_id)
            .where(
                User.is_active.is_(True),
                or_(User.role == UserRole.owner, GroupMember.role == MemberRole.owner),
            )
        )
        return result.scalar_one() or 0

    async def update_role(self, identifier: str, role: MemberRole) -> bool:
        member = await self.get_member(identifier)
        if not member:
            return False

        await self.db.execute(
            update(User)
            .where(User.session_id == member["session_id"])
            .values(role=UserRole(role.value), updated_at=datetime.utcnow())
        )
        result = await self.db.execute(
            update(GroupMember)
            .where(GroupMember.user_session_id == member["session_id"])
            .values(role=role)
        )
        if result.rowcount == 0:
            self.db.add(GroupMember(user_session_id=member["session_id"], role=role))
        await self.db.commit()
        return True

    @staticmethod
    def _response_role(user_role: UserRole | None, member_role: MemberRole | None) -> MemberRole:
        roles = []
        if user_role and user_role.value in {item.value for item in MemberRole}:
            roles.append(MemberRole(user_role.value))
        if member_role:
            roles.append(member_role)
        if not roles:
            return MemberRole.member

        rank = {
            MemberRole.owner: 0,
            MemberRole.admin: 1,
            MemberRole.member: 2,
        }
        return min(roles, key=lambda role: rank[role])
