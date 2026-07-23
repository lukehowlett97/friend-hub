from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.message import Base


class HomeAppearance(Base):
    __tablename__ = "home_appearance"
    __table_args__ = (
        UniqueConstraint("group_id", name="uq_home_appearance_group"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, unique=True)
    cover_photo_id = Column(Integer, ForeignKey("photos.id", ondelete="SET NULL"), nullable=True)
    cover_position_x = Column(SmallInteger, nullable=False, default=50, server_default="50")
    cover_position_y = Column(SmallInteger, nullable=False, default=50, server_default="50")
    overlay_strength = Column(SmallInteger, nullable=False, default=50, server_default="50")
    blur_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    header_icon = Column(String(40), nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, server_default="NOW()")
    updated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
