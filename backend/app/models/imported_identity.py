from datetime import datetime
import uuid

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.message import Base


class ImportedIdentity(Base):
    __tablename__ = "imported_identities"
    __table_args__ = (
        Index("idx_imported_identities_source", "source"),
        Index("idx_imported_identities_normalised_name", "normalised_name"),
        Index("idx_imported_identities_linked_user_id", "linked_user_id"),
        Index("idx_imported_identities_status", "status"),
        Index("idx_imported_identities_source_display_name", "source", "source_display_name"),
        Index("idx_imported_identities_source_normalised_name", "source", "normalised_name"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(64), nullable=False, default="messenger", server_default="messenger")
    source_participant_id = Column(String(255), nullable=True)
    source_display_name = Column(String(255), nullable=False)
    normalised_name = Column(String(255), nullable=False)
    linked_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(24), nullable=False, default="unlinked", server_default="unlinked")
    message_count = Column(Integer, nullable=False, default=0, server_default="0")
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    confidence_score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, server_default=text("NOW()"))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=text("NOW()"),
    )

    linked_user = relationship("User", foreign_keys=[linked_user_id])
