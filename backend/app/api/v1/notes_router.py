from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.service import user_payload
from app.domains.notes.schemas import (
    EDIT_MODES,
    NOTE_TYPES,
    NoteCommentCreateRequest,
    NoteCommentsResponse,
    NoteCreateRequest,
    NoteDetailResponse,
    NoteResponse,
    NoteRevisionsResponse,
    NoteRevisionResponse,
    NotesListResponse,
    NoteUpdateRequest,
)
from app.domains.notes.service import NoteService
from app.domains.rooms.dependencies import get_current_user, require_room_member
from app.models.database import get_db_session
from app.models.message import User
from app.models.note import NoteRevision
from app.models.planning import Comment
from app.models.room import Room

router = APIRouter(prefix="/api/v1/notes", tags=["notes"])


async def _note_or_404(db: AsyncSession, note_id: int, room: Room):
    note = await NoteService(db).repo.get(note_id, room.id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.get("", response_model=NotesListResponse)
async def list_notes(
    q: str | None = None,
    note_type: str | None = None,
    pinned: bool | None = None,
    sort: str = "updated",
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    clean_q = (q or "").strip() or None
    clean_type = (note_type or "").strip().lower() or None
    if clean_type and clean_type not in NOTE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid note_type")
    clean_sort = sort if sort in {"updated", "created"} else "updated"
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)

    svc = NoteService(db)
    rows, total = await svc.repo.list(
        room.id,
        q=clean_q,
        note_type=clean_type,
        pinned=pinned,
        sort=clean_sort,
        limit=safe_limit,
        offset=safe_offset,
    )
    note_ids = [note.id for note, *_ in rows]
    comment_counts = await svc.repo.comment_counts(note_ids)
    revision_counts = await svc.repo.revision_counts(note_ids)
    notes = [
        await svc.note_payload(
            note,
            user,
            room,
            creator=creator,
            hub_item=hub_item,
            comment_count=comment_counts.get(note.id, 0),
            revision_count=revision_counts.get(note.id, 0),
        )
        for note, creator, hub_item in rows
    ]
    return {"notes": notes, "total": total}


@router.post("", response_model=NoteDetailResponse)
async def create_note(
    request: NoteCreateRequest,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    if (request.edit_mode or "owner_only").strip().lower() not in EDIT_MODES:
        raise HTTPException(status_code=400, detail="Invalid edit_mode")
    note = await NoteService(db).create(request, user, room)
    return {"note": await NoteService(db).note_payload(note, user, room, creator=user)}


@router.get("/{note_id}", response_model=NoteDetailResponse)
async def get_note(
    note_id: int,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    svc = NoteService(db)
    note = await _note_or_404(db, note_id, room)
    return {"note": await svc.note_payload(note, user, room)}


@router.patch("/{note_id}", response_model=NoteDetailResponse)
async def update_note(
    note_id: int,
    request: NoteUpdateRequest,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    svc = NoteService(db)
    note = await _note_or_404(db, note_id, room)
    note = await svc.update(note, request, user, room)
    return {"note": await svc.note_payload(note, user, room)}


@router.delete("/{note_id}")
async def delete_note(
    note_id: int,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    note = await _note_or_404(db, note_id, room)
    await NoteService(db).archive(note, user, room)
    return {"status": "archived"}


@router.post("/{note_id}/pin", response_model=NoteDetailResponse)
async def pin_note(
    note_id: int,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    svc = NoteService(db)
    note = await _note_or_404(db, note_id, room)
    note = await svc.set_pinned(note, user, room, True)
    return {"note": await svc.note_payload(note, user, room)}


@router.delete("/{note_id}/pin", response_model=NoteDetailResponse)
async def unpin_note(
    note_id: int,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    svc = NoteService(db)
    note = await _note_or_404(db, note_id, room)
    note = await svc.set_pinned(note, user, room, False)
    return {"note": await svc.note_payload(note, user, room)}


@router.get("/{note_id}/revisions", response_model=NoteRevisionsResponse)
async def list_note_revisions(
    note_id: int,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    await _note_or_404(db, note_id, room)
    rows = (await db.execute(
        select(NoteRevision, User)
        .outerjoin(User, NoteRevision.changed_by_user_id == User.id)
        .where(NoteRevision.note_id == note_id)
        .order_by(desc(NoteRevision.created_at))
    )).fetchall()
    revisions = [
        {
            "id": revision.id,
            "note_id": revision.note_id,
            "changed_by_user_id": str(revision.changed_by_user_id) if revision.changed_by_user_id else None,
            "changer": user_payload(changer) if changer else None,
            "before_title": revision.before_title,
            "after_title": revision.after_title,
            "before_body": revision.before_body,
            "after_body": revision.after_body,
            "before_note_type": revision.before_note_type,
            "after_note_type": revision.after_note_type,
            "before_edit_mode": revision.before_edit_mode,
            "after_edit_mode": revision.after_edit_mode,
            "created_at": revision.created_at.isoformat() if revision.created_at else None,
        }
        for revision, changer in rows
    ]
    return {"revisions": revisions, "total": len(revisions)}


@router.get("/{note_id}/comments", response_model=NoteCommentsResponse)
async def list_note_comments(
    note_id: int,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    await _note_or_404(db, note_id, room)
    rows = (await db.execute(
        select(Comment, User)
        .outerjoin(User, Comment.created_by_user_id == User.id)
        .where(Comment.target_type == "note", Comment.target_id == note_id)
        .order_by(Comment.created_at.asc())
    )).fetchall()
    comments = [
        {
            "id": comment.id,
            "target_type": comment.target_type,
            "target_id": comment.target_id,
            "content": comment.content,
            "creator": user_payload(creator) if creator else None,
            "created_at": comment.created_at.isoformat() if comment.created_at else None,
            "updated_at": comment.updated_at.isoformat() if comment.updated_at else None,
        }
        for comment, creator in rows
    ]
    return {"comments": comments, "total": len(comments)}


@router.post("/{note_id}/comments")
async def create_note_comment(
    note_id: int,
    request: NoteCommentCreateRequest,
    user: User = Depends(get_current_user),
    room: Room = Depends(require_room_member),
    db: AsyncSession = Depends(get_db_session),
):
    note = await _note_or_404(db, note_id, room)
    comment = await NoteService(db).create_comment(note, user, request.content)
    return {"status": "created", "id": comment.id}

