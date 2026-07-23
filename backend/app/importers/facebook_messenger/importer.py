"""Database importer for normalized Messenger messages."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from typing import Any, Iterable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_photo_upload_path, get_settings
from app.domains.image_embeddings.service import PhotoEmbeddingJobService
from app.domains.photos.service import ensure_photo_storage_capacity, process_photo_upload
from app.domains.videos.service import (
    process_video, get_video_upload_path,
    get_audio_upload_path, probe_duration,
    ACCEPTED_VIDEO_TYPES, ACCEPTED_AUDIO_TYPES,
)
from app.domains.identity.repository import normalise_identity_name
from app.models.import_tracking import ExternalIdentity, ImportBatch, ImportedMessageSource
from app.models.imported_identity import ImportedIdentity
from app.models.member import GroupMember, MemberRole
from app.models.photo import Photo
from app.models.planning import Group
from app.models.room import DEFAULT_ROOM_ID, Room
from app.models.reaction import Reaction
from app.models.message import Message, User, UserRole
from app.models.video import Video, AudioFile

from . import PROVIDER
from .discovery import inspect_chat
from .encoding import repair_text
from .parser import MEDIA_KEYS, normalize_messages, parse_chat_messages, source_hash
from .models import NormalizedMessage, ParsedMessage
from .sender_map import mapped_sender_names, resolve_mapped_user


MAX_MESSAGE_CONTENT_LENGTH = 1000
PLACEHOLDER_NAMESPACE = uuid.UUID("9513be55-5ee9-4385-8cd0-8b33a042db0d")
SUPPORTED_MEDIA_KEYS = ("photos", "gifs", "videos", "audio_files", "audio")


@dataclass(frozen=True)
class ImportSummary:
    batch_id: int
    status: str
    source_thread_path: str
    target_room_id: str | None
    message_count: int
    imported_count: int
    reaction_count: int
    skipped_count: int
    media_count: int
    error_count: int
    errors: tuple[dict, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DryRunSummary:
    title: str
    source_thread_path: str
    target_room_id: str
    participant_names: tuple[str, ...]
    mapped_senders: tuple[str, ...]
    unmapped_senders: tuple[str, ...]
    message_count: int
    text_count: int
    supported_media_count: int
    unsupported_media_count: int
    reaction_count: int
    duplicate_count: int
    oldest_at: str | None
    newest_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


@dataclass(frozen=True)
class ImportedContent:
    content: str
    photo: Photo | None = None
    video: Video | None = None
    audio: AudioFile | None = None
    should_queue_embedding: bool = False


async def dry_run_chat(
    export_root: Path | str,
    chat_folder: str,
    target_room_id: str,
    db: AsyncSession,
    sender_map: dict[str, dict[str, str]] | None = None,
) -> DryRunSummary:
    chat_path = resolve_chat_dir(export_root, chat_folder)
    chat = inspect_chat(chat_path)
    if chat is None:
        raise ValueError(f"No Messenger chat found at {chat_path}")
    await _validate_target_room(db, target_room_id)

    parsed = parse_chat_messages(chat_path)
    records = _records_for_import(parsed, chat.thread_path, include_supported_media=True)
    existing = await _existing_source_hashes(db, [record.source_hash for record in records])
    sender_map = sender_map or {}
    participant_names = await _participant_names(chat_path)
    record_senders = {record.sender_name for record in records}
    mapped = record_senders & mapped_sender_names(sender_map)

    return DryRunSummary(
        title=chat.title,
        source_thread_path=chat.thread_path,
        target_room_id=target_room_id,
        participant_names=tuple(sorted(participant_names)),
        mapped_senders=tuple(sorted(mapped)),
        unmapped_senders=tuple(sorted(record_senders - mapped)),
        message_count=len(parsed),
        text_count=sum(1 for record in records if not _is_media_record(record)),
        supported_media_count=sum(1 for record in records if _is_media_record(record)),
        unsupported_media_count=sum(1 for message in parsed if _unsupported_media_count(message.raw)),
        reaction_count=sum(len(message.raw.get("reactions") or []) for message in parsed),
        duplicate_count=len(existing),
        oldest_at=chat.oldest_at.isoformat() if chat.oldest_at else None,
        newest_at=chat.newest_at.isoformat() if chat.newest_at else None,
    )


async def import_chat(
    chat_dir: Path | str,
    db: AsyncSession,
    imported_by_user_id=None,
    chunk_size: int = 500,
    target_room_id: str | None = None,
    sender_map: dict[str, dict[str, str]] | None = None,
    export_root: Path | str | None = None,
) -> ImportSummary:
    chat_path = Path(chat_dir)
    chat = inspect_chat(chat_path)
    if chat is None:
        raise ValueError(f"No Messenger chat found at {chat_path}")
    target_group_id = await _target_group_id(db, target_room_id) if target_room_id is not None else None
    target_room_uuid = await _target_room_uuid(db, target_room_id) if target_room_id is not None else DEFAULT_ROOM_ID

    parsed = parse_chat_messages(chat_path)
    normalized = normalize_messages(parsed, chat.thread_path)
    import_records = _records_for_import(parsed, chat.thread_path, include_supported_media=True)
    batch = ImportBatch(
        provider=PROVIDER,
        source_path=str(chat_path),
        source_thread_path=chat.thread_path,
        target_room_id=target_room_id,
        status="running",
        message_count=len(parsed),
        media_count=sum(1 for record in import_records if _is_media_record(record)),
        skipped_count=normalized.skipped_empty_count + sum(1 for message in parsed if _unsupported_media_count(message.raw)),
        imported_by_user_id=imported_by_user_id,
        errors=[],
    )
    db.add(batch)
    await db.flush()
    batch_id = batch.id
    initial_skipped_count = batch.skipped_count or 0
    await db.commit()

    imported_count = 0
    reaction_count = 0
    errors: list[dict] = []
    skipped_count = initial_skipped_count
    touched_identity_ids: set[uuid.UUID] = set()
    sender_map = sender_map or {}
    export_root_path = Path(export_root) if export_root else chat_path.parents[3] if len(chat_path.parents) >= 4 else chat_path

    total_records = len(import_records)
    processed = 0
    print(f"Importing {total_records} records (chunk size {chunk_size})...", file=sys.stderr, flush=True)

    try:
        for chunk in _chunks(import_records, chunk_size):
            existing_hashes = await _existing_source_hashes(db, [message.source_hash for message in chunk], room_id=target_room_uuid)
            for message in chunk:
                if message.source_hash in existing_hashes:
                    skipped_count += 1
                    continue
                if len(message.content) > MAX_MESSAGE_CONTENT_LENGTH:
                    skipped_count += 1
                    errors.append({
                        "type": "content_too_long",
                        "sender_name": message.sender_name,
                        "timestamp_ms": message.timestamp_ms,
                        "length": len(message.content),
                    })
                    continue

                user, imported_identity = await _resolve_import_sender(db, message.sender_name, sender_map)
                if target_group_id is not None:
                    await _ensure_group_member(db, user, target_group_id)
                try:
                    imported_content = await _content_for_import_record(
                        db,
                        message,
                        chat_path,
                        export_root_path,
                        user,
                        target_room_uuid,
                    )
                except FileNotFoundError as exc:
                    skipped_count += 1
                    errors.append({
                        "type": "media_file_not_found",
                        "sender_name": message.sender_name,
                        "timestamp_ms": message.timestamp_ms,
                        "source_hash": message.source_hash,
                        "message": str(exc),
                    })
                    continue

                if len(imported_content.content) > MAX_MESSAGE_CONTENT_LENGTH:
                    skipped_count += 1
                    errors.append({
                        "type": "content_too_long",
                        "sender_name": message.sender_name,
                        "timestamp_ms": message.timestamp_ms,
                        "length": len(imported_content.content),
                    })
                    continue

                db_message = Message(
                    user_session_id=user.session_id,
                    user_id=user.id,
                    imported_identity_id=imported_identity.id,
                    content=imported_content.content,
                    created_at=message.sent_at,
                    is_imported=True,
                    room_id=target_room_uuid,
                )
                db.add(db_message)
                await db.flush()
                if imported_content.photo is not None:
                    imported_content.photo.message_id = db_message.id
                    imported_content.photo.import_batch_id = batch.id
                    if target_room_id is not None:
                        imported_content.photo.conversation_id = str(target_room_id)
                    if imported_content.should_queue_embedding:
                        await PhotoEmbeddingJobService(db).create_pending_embedding_job(imported_content.photo.id)
                if imported_content.video is not None:
                    imported_content.video.message_id = db_message.id
                    imported_content.video.import_batch_id = batch.id
                    if target_room_id is not None:
                        imported_content.video.conversation_id = str(target_room_id)
                if imported_content.audio is not None:
                    imported_content.audio.message_id = db_message.id
                    imported_content.audio.import_batch_id = batch.id
                    if target_room_id is not None:
                        imported_content.audio.conversation_id = str(target_room_id)
                _record_imported_identity_message(imported_identity, message.sent_at)
                touched_identity_ids.add(imported_identity.id)

                await _upsert_imported_message_source(
                    db,
                    batch_id=batch.id,
                    message_id=db_message.id,
                    record=message,
                    target_room_id=target_room_id,
                )
                reaction_count += await _import_reactions(db, db_message, message, sender_map)
                imported_count += 1

            await db.flush()
            await _recount_imported_identities(db, touched_identity_ids)
            await db.commit()
            processed += len(chunk)
            pct = processed * 100 // total_records if total_records else 100
            print(f"  {processed}/{total_records} ({pct}%)  imported={imported_count}  skipped={skipped_count}  errors={len(errors)}", file=sys.stderr, flush=True)

        status = "completed"
    except Exception as exc:
        status = "failed"
        errors.append({"type": "import_failed", "message": str(exc)})
        await db.rollback()
    finally:
        await db.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch_id)
            .values(
                status=status,
                completed_at=datetime.utcnow(),
                imported_count=imported_count,
                skipped_count=skipped_count,
                media_count=sum(1 for record in import_records if _is_media_record(record)),
                error_count=len(errors),
                errors=errors,
            )
        )
        await db.commit()

    return ImportSummary(
        batch_id=batch_id,
        status=status,
        source_thread_path=chat.thread_path,
        target_room_id=target_room_id,
        message_count=len(parsed),
        imported_count=imported_count,
        reaction_count=reaction_count,
        skipped_count=skipped_count,
        media_count=sum(1 for record in import_records if _is_media_record(record)),
        error_count=len(errors),
        errors=tuple(errors),
    )


async def _existing_source_hashes(db: AsyncSession, source_hashes: list[str], room_id=None) -> set[str]:
    if not source_hashes:
        return set()
    stmt = (
        select(ImportedMessageSource.source_hash)
        .join(Message, ImportedMessageSource.message_id == Message.id)
        .where(
            ImportedMessageSource.provider == PROVIDER,
            ImportedMessageSource.source_hash.in_(source_hashes),
        )
    )
    if room_id is not None:
        stmt = stmt.where(Message.room_id == room_id)
    result = await db.execute(stmt)
    return set(result.scalars().all())


async def _upsert_imported_message_source(
    db: AsyncSession,
    *,
    batch_id: int,
    message_id: int,
    record: NormalizedMessage,
    target_room_id: str | None,
) -> None:
    result = await db.execute(
        select(ImportedMessageSource).where(
            ImportedMessageSource.provider == PROVIDER,
            ImportedMessageSource.source_hash == record.source_hash,
        )
    )
    source = result.scalar_one_or_none()
    values = {
        "batch_id": batch_id,
        "provider": PROVIDER,
        "source_thread_path": record.source_thread_path,
        "target_room_id": target_room_id,
        "source_hash": record.source_hash,
        "message_id": message_id,
        "raw_sender_name": record.sender_name,
        "source_timestamp": record.sent_at,
        "raw_metadata": {**record.raw_metadata, "target_room_id": target_room_id},
    }
    if source is None:
        db.add(ImportedMessageSource(**values))
        return

    for key, value in values.items():
        setattr(source, key, value)


def resolve_chat_dir(export_root: Path | str, chat_folder: str) -> Path:
    root = Path(export_root).expanduser().resolve()
    requested = Path(chat_folder).expanduser()
    if requested.is_absolute() and (requested / "message_1.json").exists():
        return requested.resolve()

    direct = (root / requested).resolve()
    if direct.exists() and any(direct.glob("message_*.json")):
        return direct

    matches = [path for path in root.rglob("message_1.json") if path.parent.name == chat_folder]
    if not matches:
        matches = [path for path in root.rglob("message_1.json") if chat_folder in str(path.parent)]
    if not matches:
        raise FileNotFoundError(f"Could not find Messenger chat folder {chat_folder!r} under {root}")
    if len(matches) > 1:
        raise ValueError(f"Chat folder {chat_folder!r} matched multiple paths: {[str(path.parent) for path in matches]}")
    return matches[0].parent.resolve()


async def _resolve_import_sender(
    db: AsyncSession,
    sender_name: str,
    sender_map: dict[str, dict[str, str]] | None = None,
) -> tuple[User, ImportedIdentity]:
    external_name = repair_text(sender_name).strip()
    mapped_user = await resolve_mapped_user(db, external_name, sender_map or {})
    imported_identity = await _upsert_imported_identity(db, external_name, mapped_user)
    if mapped_user is not None:
        await _upsert_external_identity(db, external_name, mapped_user)
        return mapped_user, imported_identity

    if imported_identity.linked_user_id:
        result = await db.execute(select(User).where(User.id == imported_identity.linked_user_id))
        linked_user = result.scalar_one_or_none()
        if linked_user:
            await _upsert_external_identity(db, external_name, linked_user)
            return linked_user, imported_identity

    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER,
            ExternalIdentity.external_name == external_name,
        )
    )
    identity = result.scalar_one_or_none()
    if identity and identity.user_session_id:
        result = await db.execute(select(User).where(User.session_id == identity.user_session_id))
        user = result.scalar_one_or_none()
        if user:
            await _mark_import_placeholder_user(user)
            return user, imported_identity

    result = await db.execute(select(User).where(User.nickname == external_name))
    user = result.scalar_one_or_none()
    if user is None:
        user = await _create_placeholder_user(db, external_name)
    await _mark_import_placeholder_user(user)

    await _upsert_external_identity(db, external_name, user)
    return user, imported_identity


async def _upsert_imported_identity(
    db: AsyncSession,
    external_name: str,
    linked_user: User | None = None,
) -> ImportedIdentity:
    normalised_name = normalise_identity_name(external_name)
    result = await db.execute(
        select(ImportedIdentity).where(
            ImportedIdentity.source == PROVIDER,
            ImportedIdentity.normalised_name == normalised_name,
        )
    )
    identity = result.scalar_one_or_none()
    if identity is None:
        identity = ImportedIdentity(
            source=PROVIDER,
            source_display_name=external_name,
            normalised_name=normalised_name,
            linked_user_id=linked_user.id if linked_user else None,
            status="linked" if linked_user else "unlinked",
            message_count=0,
        )
        db.add(identity)
    else:
        identity.source_display_name = identity.source_display_name or external_name
        if linked_user and not identity.linked_user_id:
            identity.linked_user_id = linked_user.id
            identity.status = "linked"
    await db.flush()
    return identity


def _record_imported_identity_message(identity: ImportedIdentity, sent_at: datetime) -> None:
    identity.message_count = (identity.message_count or 0) + 1
    if identity.first_seen_at is None or sent_at < identity.first_seen_at:
        identity.first_seen_at = sent_at
    if identity.last_seen_at is None or sent_at > identity.last_seen_at:
        identity.last_seen_at = sent_at
    identity.updated_at = datetime.utcnow()


async def _recount_imported_identities(db: AsyncSession, identity_ids: set[uuid.UUID]) -> None:
    if not identity_ids:
        return
    result = await db.execute(
        select(
            Message.imported_identity_id,
            func.count(Message.id),
            func.min(Message.created_at),
            func.max(Message.created_at),
        )
        .where(Message.imported_identity_id.in_(identity_ids))
        .group_by(Message.imported_identity_id)
    )
    for identity_id, message_count, first_seen_at, last_seen_at in result.all():
        # Strip timezone info — the DB column is TIMESTAMP WITHOUT TIME ZONE
        if first_seen_at is not None and hasattr(first_seen_at, 'tzinfo') and first_seen_at.tzinfo is not None:
            first_seen_at = first_seen_at.replace(tzinfo=None)
        if last_seen_at is not None and hasattr(last_seen_at, 'tzinfo') and last_seen_at.tzinfo is not None:
            last_seen_at = last_seen_at.replace(tzinfo=None)
        await db.execute(
            update(ImportedIdentity)
            .where(ImportedIdentity.id == identity_id)
            .values(
                message_count=message_count,
                first_seen_at=first_seen_at,
                last_seen_at=last_seen_at,
                updated_at=datetime.utcnow(),
            )
        )


async def _mark_import_placeholder_user(user: User) -> None:
    if user.is_active:
        return
    user.user_type = "system"
    user.status = "deactivated"
    user.hidden_from_member_list = True
    user.deactivated_at = user.deactivated_at or datetime.utcnow()


async def _upsert_external_identity(db: AsyncSession, external_name: str, user: User) -> None:
    result = await db.execute(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER,
            ExternalIdentity.external_name == external_name,
        )
    )
    identity = result.scalar_one_or_none()
    if identity is None:
        db.add(ExternalIdentity(
            provider=PROVIDER,
            external_name=external_name,
            user_id=user.id,
            user_session_id=user.session_id,
        ))
    else:
        identity.user_id = user.id
        identity.user_session_id = user.session_id

    await db.flush()


async def _create_placeholder_user(db: AsyncSession, external_name: str) -> User:
    placeholder_id = uuid.uuid5(PLACEHOLDER_NAMESPACE, f"{PROVIDER}:{external_name}")
    result = await db.execute(select(User).where(User.session_id == placeholder_id))
    user = result.scalar_one_or_none()
    if user is not None:
        return user

    user = User(
        session_id=placeholder_id,
        id=placeholder_id,
        nickname=await _available_placeholder_nickname(db, external_name),
        role=UserRole.member,
        is_active=False,
        user_type="system",
        status="deactivated",
        hidden_from_member_list=True,
        deactivated_at=datetime.utcnow(),
        joined_at=datetime.utcnow(),
        last_seen=datetime.utcnow(),
        last_seen_at=datetime.utcnow(),
    )
    db.add(user)
    await db.flush()
    return user


async def _available_placeholder_nickname(db: AsyncSession, external_name: str) -> str:
    base = external_name.strip()[:50] or "Imported Messenger User"
    if not await _nickname_exists(db, base):
        return base

    suffix = " (imported)"
    candidate = f"{base[:50 - len(suffix)]}{suffix}"
    if not await _nickname_exists(db, candidate):
        return candidate

    digest = uuid.uuid5(PLACEHOLDER_NAMESPACE, external_name).hex[:6]
    suffix = f" ({digest})"
    return f"{base[:50 - len(suffix)]}{suffix}"


async def _nickname_exists(db: AsyncSession, nickname: str) -> bool:
    result = await db.execute(select(User.session_id).where(User.nickname == nickname))
    return result.scalar_one_or_none() is not None


async def _validate_target_room(db: AsyncSession, target_room_id: str) -> None:
    await _target_group_id(db, target_room_id)
    await _target_room_uuid(db, target_room_id)


async def _target_group_id(db: AsyncSession, target_room_id: str) -> int:
    stmt = select(Group)
    if str(target_room_id).isdigit():
        stmt = stmt.where(Group.id == int(target_room_id))
    else:
        stmt = stmt.where(Group.slug == target_room_id)
    result = await db.execute(stmt)
    group = result.scalar_one_or_none()
    if group is None:
        raise ValueError(f"Target room/group does not exist: {target_room_id}")
    return group.id


async def _target_room_uuid(db: AsyncSession, target_room_id: str) -> uuid.UUID:
    stmt = select(Room)
    try:
        room_uuid = uuid.UUID(str(target_room_id))
    except ValueError:
        room_uuid = None

    if room_uuid is not None:
        stmt = stmt.where(Room.id == room_uuid)
    else:
        stmt = stmt.where(Room.slug == target_room_id)

    result = await db.execute(stmt)
    room = result.scalar_one_or_none()
    if room is None:
        raise ValueError(f"Target room does not exist: {target_room_id}")
    # Ensure we return a standard uuid.UUID, not an asyncpg UUID type,
    # so SQLAlchemy includes it correctly in INSERT statements.
    return uuid.UUID(str(room.id))


async def _ensure_group_member(db: AsyncSession, user: User, group_id: int) -> None:
    result = await db.execute(
        select(GroupMember).where(GroupMember.user_session_id == user.session_id)
    )
    membership = result.scalar_one_or_none()
    if membership is None:
        db.add(GroupMember(
            group_id=group_id,
            user_session_id=user.session_id,
            role=MemberRole.member,
        ))
    elif membership.group_id is None:
        membership.group_id = group_id


def _records_for_import(
    messages: Iterable[ParsedMessage],
    source_thread_path: str,
    *,
    include_supported_media: bool,
) -> tuple[NormalizedMessage, ...]:
    records = list(normalize_messages(messages, source_thread_path).messages)
    if not include_supported_media:
        return tuple(records)

    for message in messages:
        media_entries = _supported_media_entries(message.raw)
        if not media_entries:
            continue
        sent_at = datetime.fromtimestamp(message.timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        for index, entry in enumerate(media_entries):
            uri_payload = f"{entry['kind']}:{entry['uri']}:{index}"
            raw_metadata = {
                "source_file": message.source_file.name,
                "keys": sorted(message.raw.keys()),
                "media_entries": [entry],
                "reactions": message.raw.get("reactions") or [],
            }
            records.append(NormalizedMessage(
                sender_name=repair_text(message.sender_name).strip(),
                content=uri_payload,
                sent_at=sent_at,
                timestamp_ms=message.timestamp_ms,
                source_thread_path=source_thread_path,
                source_hash=source_hash(
                    source_thread_path=source_thread_path,
                    sender_name=message.sender_name,
                    timestamp_ms=message.timestamp_ms,
                    content=uri_payload,
                    raw=message.raw,
                ),
                raw_metadata=raw_metadata,
            ))
    return tuple(sorted(records, key=lambda record: record.timestamp_ms))


def _supported_media_entries(raw: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for key in SUPPORTED_MEDIA_KEYS:
        for item in raw.get(key) or []:
            if isinstance(item, dict) and item.get("uri"):
                entries.append({"kind": key, "uri": item["uri"]})
    return entries


def _unsupported_media_count(raw: dict[str, Any]) -> int:
    if raw.get("content"):
        return 0
    if _supported_media_entries(raw):
        return 0
    return 1 if any(key in raw for key in MEDIA_KEYS) or raw.get("call_duration") else 0


def _is_media_record(record: NormalizedMessage) -> bool:
    return bool(record.raw_metadata.get("media_entries"))


async def _content_for_import_record(
    db: AsyncSession,
    record: NormalizedMessage,
    chat_path: Path,
    export_root: Path,
    user: User,
    room_id,
) -> ImportedContent:
    entries = record.raw_metadata.get("media_entries") or []
    if not entries:
        return ImportedContent(content=record.content)

    entry = entries[0]
    source_path = _resolve_media_source(entry["uri"], chat_path, export_root)
    if entry["kind"] == "photos":
        return await _import_photo_message(db, source_path, user, record, room_id)
    if entry["kind"] == "gifs":
        return await _import_gif_message(db, source_path, user, record, room_id)
    if entry["kind"] == "videos":
        return await _import_video_message(db, source_path, user, record, room_id)
    if entry["kind"] in {"audio_files", "audio"}:
        return await _import_audio_message(db, source_path, user, record, room_id)
    return ImportedContent(content=record.content)


def _resolve_media_source(uri: str, chat_path: Path, export_root: Path) -> Path:
    fname = Path(uri).name
    folder = Path(uri).parent.name  # e.g. "photos" or "gifs"
    candidates = [
        export_root / uri,
        export_root / uri.removeprefix("your_facebook_activity/"),
        export_root / "your_facebook_activity" / uri,
        chat_path / uri,
        chat_path / fname,
        chat_path / folder / fname,        # e.g. chat_path/photos/filename.jpg
        chat_path / "photos" / fname,      # fetched exports put photos here
        chat_path / "gifs" / fname,
        chat_path / "videos" / fname,
        chat_path / "audio_files" / fname,
        chat_path / "files" / fname,
        chat_path / Path(uri).parent.name / fname,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Media file not found for Messenger URI: {uri}")


async def _import_photo_message(
    db: AsyncSession,
    source_path: Path,
    user: User,
    record: NormalizedMessage,
    room_id,
) -> ImportedContent:
    settings = get_settings()
    content = source_path.read_bytes()
    processed = process_photo_upload(
        content,
        display_max_width=settings.photo_display_max_width,
        thumbnail_max_width=settings.photo_thumbnail_max_width,
        jpeg_quality=settings.photo_jpeg_quality,
    )
    upload_dir = get_photo_upload_path()
    upload_dir.mkdir(parents=True, exist_ok=True)
    ensure_photo_storage_capacity(upload_dir, processed.total_size_bytes, settings.photo_storage_max_bytes)

    photo_id = uuid.uuid5(PLACEHOLDER_NAMESPACE, f"{record.source_hash}:photo").hex
    filename = f"{photo_id}{processed.extension}"
    thumbnail_filename = f"{photo_id}_thumb{processed.extension}"
    (upload_dir / filename).write_bytes(processed.display_bytes)
    (upload_dir / thumbnail_filename).write_bytes(processed.thumbnail_bytes)
    photo = Photo(
        filename=filename,
        thumbnail_filename=thumbnail_filename,
        original_filename=source_path.name,
        content_type=processed.content_type,
        size_bytes=processed.size_bytes,
        file_size_bytes=processed.size_bytes,
        width=processed.width,
        height=processed.height,
        thumbnail_size_bytes=processed.thumbnail_size_bytes,
        source_type="messenger_import",
        storage_path=f"/uploads/photos/{filename}",
        tags=["imported", "facebook_messenger"],
        uploaded_by_session_id=user.session_id,
        created_at=record.sent_at,
        taken_at=record.sent_at,
        room_id=room_id,
    )
    db.add(photo)
    await db.flush()
    return ImportedContent(
        content=f"Photo: {source_path.name}\n/uploads/photos/{filename}",
        photo=photo,
        should_queue_embedding=True,
    )


async def _import_gif_message(
    db: AsyncSession,
    source_path: Path,
    user: User,
    record: NormalizedMessage,
    room_id,
) -> ImportedContent:
    upload_dir = get_photo_upload_path()
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower() or ".gif"
    filename = f"{uuid.uuid5(PLACEHOLDER_NAMESPACE, f'{record.source_hash}:gif').hex}{suffix}"
    destination = upload_dir / filename
    copy2(source_path, destination)
    photo = Photo(
        filename=filename,
        thumbnail_filename=None,
        original_filename=source_path.name,
        content_type="image/gif",
        size_bytes=destination.stat().st_size,
        file_size_bytes=destination.stat().st_size,
        source_type="messenger_import",
        storage_path=f"/uploads/photos/{filename}",
        tags=["imported", "facebook_messenger", "gif"],
        uploaded_by_session_id=user.session_id,
        created_at=record.sent_at,
        taken_at=record.sent_at,
        room_id=room_id,
    )
    db.add(photo)
    await db.flush()
    return ImportedContent(content=f"Photo: {source_path.name}\n/uploads/photos/{filename}", photo=photo)


async def _import_video_message(
    db: AsyncSession,
    source_path: Path,
    user: User,
    record: NormalizedMessage,
    room_id,
) -> ImportedContent:
    content = source_path.read_bytes()
    suffix = source_path.suffix.lower() or ".mp4"
    try:
        processed = process_video(content, original_suffix=suffix)
    except Exception:
        # If ffmpeg fails (corrupt file etc.), store original as-is
        processed = None

    upload_dir = get_video_upload_path()
    upload_dir.mkdir(parents=True, exist_ok=True)
    vid_id = uuid.uuid5(PLACEHOLDER_NAMESPACE, f"{record.source_hash}:video").hex

    if processed:
        filename = f"{vid_id}.mp4"
        thumb_filename = f"{vid_id}_thumb.jpg" if processed.thumbnail_bytes else None
        (upload_dir / filename).write_bytes(processed.video_bytes)
        if thumb_filename and processed.thumbnail_bytes:
            (upload_dir / thumb_filename).write_bytes(processed.thumbnail_bytes)
        size_bytes = processed.size_bytes
        duration = processed.duration_seconds
        width, height = processed.width, processed.height
        content_type = "video/mp4"
    else:
        filename = f"{vid_id}{suffix}"
        thumb_filename = None
        (upload_dir / filename).write_bytes(content)
        size_bytes = len(content)
        duration = 0.0
        width = height = 0
        content_type = f"video/{suffix.lstrip('.')}"

    video = Video(
        filename=filename,
        thumbnail_filename=thumb_filename,
        original_filename=source_path.name,
        content_type=content_type,
        size_bytes=size_bytes,
        duration_seconds=duration,
        width=width,
        height=height,
        source_type="messenger_import",
        storage_path=f"/uploads/videos/{filename}",
        tags=["imported", "facebook_messenger"],
        uploaded_by_session_id=user.session_id,
        created_at=record.sent_at,
        taken_at=record.sent_at,
        room_id=room_id,
    )
    db.add(video)
    await db.flush()
    thumb_url = f"/uploads/videos/{thumb_filename}" if thumb_filename else ""
    return ImportedContent(
        content=f"Video: {source_path.name}\n/uploads/videos/{filename}\n{thumb_url}".strip(),
        video=video,
    )


async def _import_audio_message(
    db: AsyncSession,
    source_path: Path,
    user: User,
    record: NormalizedMessage,
    room_id,
) -> ImportedContent:
    content = source_path.read_bytes()
    suffix = source_path.suffix.lower() or ".mp4"
    audio_id = uuid.uuid5(PLACEHOLDER_NAMESPACE, f"{record.source_hash}:audio").hex
    filename = f"{audio_id}{suffix}"

    upload_dir = get_audio_upload_path()
    upload_dir.mkdir(parents=True, exist_ok=True)
    destination = upload_dir / filename
    copy2(source_path, destination)

    duration = probe_duration(source_path)
    content_type = {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".opus": "audio/ogg",
    }.get(suffix, "audio/mpeg")

    audio = AudioFile(
        filename=filename,
        original_filename=source_path.name,
        content_type=content_type,
        size_bytes=len(content),
        duration_seconds=duration,
        source_type="messenger_import",
        storage_path=f"/uploads/audio/{filename}",
        uploaded_by_session_id=user.session_id,
        created_at=record.sent_at,
        taken_at=record.sent_at,
        room_id=room_id,
    )
    db.add(audio)
    await db.flush()
    return ImportedContent(
        content=f"Audio: {source_path.name}\n/uploads/audio/{filename}",
        audio=audio,
    )


async def _import_reactions(
    db: AsyncSession,
    message: Message,
    record: NormalizedMessage,
    sender_map: dict[str, dict[str, str]],
) -> int:
    count = 0
    for reaction in record.raw_metadata.get("reactions") or []:
        if not isinstance(reaction, dict) or not reaction.get("reaction") or not reaction.get("actor"):
            continue
        user, _identity = await _resolve_import_sender(db, reaction["actor"], sender_map)
        db.add(Reaction(
            message_id=message.id,
            user_session_id=user.session_id,
            user_id=user.id,
            emoji=repair_text(reaction["reaction"]),
            created_at=record.sent_at,
        ))
        count += 1
    return count


async def _participant_names(chat_path: Path) -> set[str]:
    from .parser import load_message_json, find_message_files

    names: set[str] = set()
    for path in find_message_files(chat_path):
        data = load_message_json(path)
        for participant in data.get("participants") or []:
            if isinstance(participant, dict) and participant.get("name"):
                names.add(repair_text(participant["name"]).strip())
    return names


def _chunks(messages: Iterable[NormalizedMessage], size: int) -> Iterable[tuple[NormalizedMessage, ...]]:
    batch: list[NormalizedMessage] = []
    for message in messages:
        batch.append(message)
        if len(batch) >= size:
            yield tuple(batch)
            batch = []
    if batch:
        yield tuple(batch)
