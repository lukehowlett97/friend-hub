from datetime import datetime
import uuid

from pydantic import BaseModel


class ImportedIdentityCreate(BaseModel):
    source: str = "messenger"
    source_participant_id: str | None = None
    source_display_name: str
    normalised_name: str | None = None
    status: str = "unlinked"
    message_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    confidence_score: float | None = None
    notes: str | None = None


class ImportedIdentityUpdate(BaseModel):
    status: str | None = None
    linked_user_id: uuid.UUID | None = None
    notes: str | None = None
    confidence_score: float | None = None


class ImportedIdentityLinkRequest(BaseModel):
    user_id: uuid.UUID


class UserCleanupUpdate(BaseModel):
    user_type: str | None = None
    status: str | None = None
    is_test_user: bool | None = None
    is_bot: bool | None = None
    hidden_from_member_list: bool | None = None

