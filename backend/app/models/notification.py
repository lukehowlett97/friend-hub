from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from app.models.message import Base

class Notification(Base):
    __tablename__ = "notifications"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type        = Column(String(50), nullable=False)
    title       = Column(String(200), nullable=False)
    body        = Column(Text, nullable=True)
    target_type = Column(String(50), nullable=True)
    target_id   = Column(Integer, nullable=True)
    is_read     = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    room_id     = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=True)
