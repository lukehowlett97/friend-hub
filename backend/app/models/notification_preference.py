"""Model for per-user notification preferences."""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.message import Base


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_messages = Column(Boolean, nullable=False, default=False)
    chat_mentions = Column(Boolean, nullable=False, default=True)
    polls = Column(Boolean, nullable=False, default=True)
    events = Column(Boolean, nullable=False, default=True)
    reminders = Column(Boolean, nullable=False, default=True)
    comments = Column(Boolean, nullable=False, default=True)
    reactions = Column(Boolean, nullable=False, default=True)
    hub_bot = Column(Boolean, nullable=False, default=True)
    push_enabled = Column(Boolean, nullable=False, default=True)
    email_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    user = relationship("User", backref="notification_preferences")

    def __repr__(self):
        return f"<NotificationPreference user_id={self.user_id}>"