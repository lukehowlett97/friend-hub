from datetime import datetime
import re
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.service import user_payload
from app.domains.notes.repository import NoteRepository
from app.domains.notes.schemas import EDIT_MODES, NOTE_TYPES, NoteCreateRequest, NoteUpdateRequest
from app.domains.rooms.repository import RoomRepository
from app.models.hub_item import HubItem, HubItemStatus
from app.models.message import User
from app.models.note import Note, NoteRevision
from app.models.planning import ActivityAction, ActivityLog, Comment, DEFAULT_GROUP_SLUG, Group
from app.models.room import Room


MAX_TITLE = 220
MAX_BODY = 20000
MAX_COMMENT = 4000
SHORT_ID_BODY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{1,18}$")


def _role_value(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role or "member")


def _is_global_admin(user: User) -> bool:
    return _role_value(user) in {"owner", "admin"}


def _clean_required(value: str | None, field: str, max_length: int) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return cleaned[:max_length]


def _clean_optional(value: str | None, max_length: int) -> str:
    if value is None:
        return ""
    return value.strip()[:max_length]


def _validate_note_type(value: str | None) -> str:
    note_type = (value or "general").strip().lower()
    if note_type not in NOTE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid note_type")
    return note_type


def _validate_edit_mode(value: str | None) -> str:
    edit_mode = (value or "owner_only").strip().lower()
    if edit_mode not in EDIT_MODES:
        raise HTTPException(status_code=400, detail="Invalid edit_mode")
    return edit_mode


def _clean_reference_tag(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate.startswith("#"):
        candidate = candidate[1:]
    if not SHORT_ID_BODY_RE.match(candidate):
        raise HTTPException(
            status_code=400,
            detail="Reference tag must start with a letter and contain only letters, numbers, hyphens or underscores (2-19 chars)",
        )
    return f"#{candidate}"


class NoteService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NoteRepository(db)

    async def default_group(self) -> Group:
        group = (await self.db.execute(select(Group).where(Group.slug == DEFAULT_GROUP_SLUG))).scalar_one_or_none()
        if group:
            return group
        group = Group(name="Friend Hub", slug=DEFAULT_GROUP_SLUG)
        self.db.add(group)
        await self.db.flush()
        return group

    async def is_room_admin(self, user: User, room: Room) -> bool:
        return _is_global_admin(user) or await RoomRepository(self.db).is_admin(room.id, user.id)

    async def can_manage(self, user: User, room: Room, note: Note) -> bool:
        if await self.is_room_admin(user, room):
            return True
        return note.created_by_user_id is not None and str(note.created_by_user_id) == str(user.id)

    async def permissions(self, user: User, room: Room, note: Note) -> dict:
        can_manage = await self.can_manage(user, room, note)
        can_edit = can_manage or note.edit_mode == "collaborative"
        return {
            "can_edit": bool(can_edit),
            "can_delete": bool(can_manage),
            "can_pin": bool(can_manage),
            "can_comment": True,
            "can_add_entry": False,
            "can_view_revisions": True,
        }

    def _hub_item_payload(self, item: HubItem | None) -> dict | None:
        if item is None:
            return None
        return {
            "id": str(item.id),
            "short_id": item.short_id,
            "type": item.item_type,
            "title": item.title,
            "body": item.body,
            "tags": item.tags or [],
            "status": item.status,
            "pinned_to_home": bool(item.pinned_to_home),
            "source_type": item.source_type,
            "source_id": item.source_id,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }

    async def note_payload(
        self,
        note: Note,
        user: User,
        room: Room,
        *,
        creator: User | None = None,
        hub_item: HubItem | None = None,
        comment_count: int | None = None,
        revision_count: int | None = None,
    ) -> dict:
        if hub_item is None:
            hub_item = await self.repo.get_hub_item(note.id, note.room_id)
        if creator is None and note.created_by_user_id:
            creator = await self.db.get(User, note.created_by_user_id)
        if comment_count is None:
            comment_count = (await self.repo.comment_counts([note.id])).get(note.id, 0)
        if revision_count is None:
            revision_count = (await self.repo.revision_counts([note.id])).get(note.id, 0)
        hub_payload = self._hub_item_payload(hub_item)
        return {
            "id": note.id,
            "room_id": str(note.room_id),
            "group_id": note.group_id,
            "room_sequence": note.room_sequence,
            "title": note.title,
            "body": note.body or "",
            "note_type": note.note_type,
            "edit_mode": note.edit_mode,
            "created_by_user_id": str(note.created_by_user_id) if note.created_by_user_id else None,
            "creator": user_payload(creator) if creator else None,
            "hub_item": hub_payload,
            "short_id": hub_payload.get("short_id") if hub_payload else None,
            "pinned_to_home": bool(hub_payload.get("pinned_to_home")) if hub_payload else False,
            "comment_count": comment_count or 0,
            "revision_count": revision_count or 0,
            "permissions": await self.permissions(user, room, note),
            "archived_at": note.archived_at.isoformat() if note.archived_at else None,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "updated_at": note.updated_at.isoformat() if note.updated_at else None,
        }

    async def _log_activity(self, group_id: int | None, user: User, action: ActivityAction, target_type: str, target_id: int | None, summary: str) -> None:
        if group_id is None:
            return
        self.db.add(ActivityLog(
            group_id=group_id,
            actor_user_id=user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary=summary[:240],
        ))

    async def _ensure_reference_tag_unique(self, room: Room, reference_tag: str, exclude_item_id=None) -> None:
        group = await self.default_group()
        stmt = select(HubItem.id).where(
            HubItem.group_id == group.id,
            HubItem.room_id == room.id,
            func.upper(HubItem.short_id) == reference_tag.upper(),
        )
        if exclude_item_id is not None:
            stmt = stmt.where(HubItem.id != exclude_item_id)
        existing = (await self.db.execute(stmt)).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"Reference tag {reference_tag} is already in use")

    async def _sync_hub_item(
        self,
        note: Note,
        user: User,
        *,
        pinned: bool | None = None,
        reference_tag: str | None = None,
    ) -> HubItem:
        group = await self.default_group()
        item = await self.repo.get_hub_item(note.id, note.room_id)
        if item is None:
            item = HubItem(
                group_id=group.id,
                room_id=note.room_id,
                item_type="note",
                source_type="note",
                source_id=note.id,
                type_sequence=note.room_sequence,
                short_id=f"#N-{note.room_sequence}",
                created_by_user_id=note.created_by_user_id,
                tags=[note.note_type] if note.note_type != "general" else [],
            )
            self.db.add(item)
        if reference_tag is not None:
            item.short_id = reference_tag
        item.group_id = group.id
        item.title = note.title[:220]
        item.body = note.body
        item.tags = [note.note_type] if note.note_type != "general" else []
        item.status = HubItemStatus.archived.value if note.archived_at else HubItemStatus.open.value
        item.archived_at = note.archived_at
        item.archived_by = note.archived_by
        item.updated_at = datetime.utcnow()
        if pinned is not None:
            item.pinned_to_home = pinned
        if note.archived_at:
            item.pinned_to_home = False
        return item

    async def create(self, request: NoteCreateRequest, user: User, room: Room) -> Note:
        group = await self.default_group()
        note = Note(
            group_id=group.id,
            room_id=room.id,
            room_sequence=await self.repo.next_room_sequence(room.id),
            title=_clean_required(request.title, "Title", MAX_TITLE),
            body=_clean_optional(request.body, MAX_BODY),
            note_type=_validate_note_type(request.note_type),
            edit_mode=_validate_edit_mode(request.edit_mode),
            created_by_user_id=user.id,
        )
        self.db.add(note)
        await self.db.flush()
        reference_tag = None
        if request.reference_tag is not None:
            reference_tag = _clean_reference_tag(request.reference_tag)
            await self._ensure_reference_tag_unique(room, reference_tag)
        await self._sync_hub_item(note, user, pinned=bool(request.is_pinned), reference_tag=reference_tag)
        await self._log_activity(group.id, user, ActivityAction.created, "note", note.id, f"{user.nickname} created note: {note.title}")
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def update(self, note: Note, request: NoteUpdateRequest, user: User, room: Room) -> Note:
        can_manage = await self.can_manage(user, room, note)
        field_set = getattr(request, "model_fields_set", None) or getattr(request, "__fields_set__", set())
        content_fields = {"title", "body"} & field_set
        settings_fields = {"note_type", "edit_mode", "is_pinned", "reference_tag"} & field_set
        if settings_fields and not can_manage:
            raise HTTPException(status_code=403, detail="Only the note creator or an admin can change note settings")
        if content_fields and not (can_manage or note.edit_mode == "collaborative"):
            raise HTTPException(status_code=403, detail="Only the note creator or an admin can edit this note")

        hub_item = await self.repo.get_hub_item(note.id, note.room_id)
        reference_tag = None
        if request.reference_tag is not None:
            reference_tag = _clean_reference_tag(request.reference_tag)
            if reference_tag.upper() != ((hub_item.short_id if hub_item else "") or "").upper():
                await self._ensure_reference_tag_unique(room, reference_tag, exclude_item_id=hub_item.id if hub_item else None)

        before = {
            "title": note.title,
            "body": note.body,
            "note_type": note.note_type,
            "edit_mode": note.edit_mode,
        }
        if request.title is not None:
            note.title = _clean_required(request.title, "Title", MAX_TITLE)
        if request.body is not None:
            note.body = _clean_optional(request.body, MAX_BODY)
        if request.note_type is not None:
            note.note_type = _validate_note_type(request.note_type)
        if request.edit_mode is not None:
            note.edit_mode = _validate_edit_mode(request.edit_mode)
        note.updated_at = datetime.utcnow()

        changed = any(before[key] != getattr(note, key) for key in before)
        if changed:
            self.db.add(NoteRevision(
                note_id=note.id,
                changed_by_user_id=user.id,
                before_title=before["title"],
                after_title=note.title,
                before_body=before["body"],
                after_body=note.body,
                before_note_type=before["note_type"],
                after_note_type=note.note_type,
                before_edit_mode=before["edit_mode"],
                after_edit_mode=note.edit_mode,
            ))
        await self._sync_hub_item(
            note,
            user,
            pinned=request.is_pinned if request.is_pinned is not None else None,
            reference_tag=reference_tag,
        )
        await self._log_activity(note.group_id, user, ActivityAction.updated, "note", note.id, f"{user.nickname} updated note: {note.title}")
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def archive(self, note: Note, user: User, room: Room) -> None:
        if not await self.can_manage(user, room, note):
            raise HTTPException(status_code=403, detail="Only the note creator or an admin can delete this note")
        note.archived_at = datetime.utcnow()
        note.archived_by = user.id
        note.updated_at = datetime.utcnow()
        await self._sync_hub_item(note, user, pinned=False)
        await self._log_activity(note.group_id, user, ActivityAction.deleted, "note", note.id, f"{user.nickname} archived note: {note.title}")
        await self.db.commit()

    async def set_pinned(self, note: Note, user: User, room: Room, pinned: bool) -> Note:
        if not await self.can_manage(user, room, note):
            raise HTTPException(status_code=403, detail="Only the note creator or an admin can pin this note")
        await self._sync_hub_item(note, user, pinned=pinned)
        await self._log_activity(note.group_id, user, ActivityAction.updated, "note", note.id, f"{user.nickname} {'pinned' if pinned else 'unpinned'} note: {note.title}")
        await self.db.commit()
        await self.db.refresh(note)
        return note

    async def create_comment(self, note: Note, user: User, content: str) -> Comment:
        comment = Comment(
            group_id=note.group_id,
            target_type="note",
            target_id=note.id,
            content=_clean_required(content, "Comment", MAX_COMMENT),
            created_by_user_id=user.id,
        )
        self.db.add(comment)
        await self.db.flush()
        await self._log_activity(note.group_id, user, ActivityAction.commented, "note", note.id, f"{user.nickname} commented on note: {note.title}")
        await self.db.commit()
        await self.db.refresh(comment)
        return comment
