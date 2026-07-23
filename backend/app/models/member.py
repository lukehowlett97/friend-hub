import enum
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, func, text
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class MemberRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id = Column(
        Integer,
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.session_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role = Column(
        Enum(MemberRole, name="member_role"),
        nullable=False,
        default=MemberRole.member,
    )
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
