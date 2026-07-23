from sqlalchemy import text, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
import uuid

Base = declarative_base()


class UserRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class User(Base):
    __tablename__ = "users"

    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    id = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=True)
    nickname = Column(String(50), nullable=False)
    display_name = Column(String(64), nullable=True)
    role = Column(Enum(UserRole, name="user_role"), nullable=False, default=UserRole.member)
    pin_hash = Column(String(255), nullable=True)
    invite_code_hash = Column(String(255), nullable=True)
    invite_code_used_at = Column(DateTime, nullable=True)
    invite_code_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default="NOW()")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    joined_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True, nullable=False)
    user_type = Column(String(24), nullable=False, default="human", server_default="human")
    status = Column(String(24), nullable=False, default="active", server_default="active")
    is_test_user = Column(Boolean, default=False, nullable=False, server_default="false")
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    is_bot = Column(Boolean, default=False, nullable=False, server_default="false")
    hidden_from_member_list = Column(Boolean, default=False, nullable=False, server_default="false")
    deactivated_at = Column(DateTime, nullable=True)
    avatar_url = Column(String(500), nullable=True)
    avatar_emoji = Column(String(8), nullable=True)
    display_role = Column(String(64), nullable=True)
    bio = Column(Text, nullable=True)

    sessions = relationship("UserSession", back_populates="user", foreign_keys="UserSession.user_id")
    messages = relationship("Message", back_populates="user", foreign_keys="Message.user_id")
    reactions = relationship("Reaction", back_populates="user", foreign_keys="Reaction.user_id")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    imported_identity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("imported_identities.id", ondelete="SET NULL"),
        nullable=True,
    )
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_at = Column(DateTime, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)
    is_imported = Column(Boolean, default=False, nullable=False, server_default="false")
    reply_to_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    hub_item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("hub_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    room_id = Column(
        UUID(as_uuid=True),
        ForeignKey("rooms.id", ondelete="CASCADE"),
        nullable=True,
    )
    is_pinned = Column(Boolean, default=False, nullable=False, server_default="false")
    pinned_at = Column(DateTime, nullable=True)
    pinned_by_session_id = Column(UUID(as_uuid=True), nullable=True)

    user = relationship("User", back_populates="messages", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "user_session_id": str(self.user_session_id),
            "user_id": str(self.user_id) if self.user_id else None,
            "imported_identity_id": str(self.imported_identity_id) if self.imported_identity_id else None,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "edited_at": self.edited_at.isoformat() if self.edited_at else None,
            "is_deleted": bool(self.is_deleted),
            "is_imported": bool(self.is_imported),
            "reply_to_id": self.reply_to_id,
            "hub_item_id": str(self.hub_item_id) if self.hub_item_id else None,
        }
