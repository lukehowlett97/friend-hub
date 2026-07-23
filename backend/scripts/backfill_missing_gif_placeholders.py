"""Backfill missing Messenger GIFs as blank chat placeholders.

This is for imports where Messenger JSON contains GIF records but the actual
GIF files are intentionally not present on the server. It creates:

- a blank imported message at the original timestamp
- a Photo row with content_type=image/gif for stats/counting
- an ImportedMessageSource row using the same source_hash scheme as importer.py

It does not create files under runtime/uploads/photos.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from sqlalchemy import select, update

from app.importers.facebook_messenger import PROVIDER
from app.importers.facebook_messenger.encoding import repair_text
from app.importers.facebook_messenger.importer import (
    PLACEHOLDER_NAMESPACE,
    _record_imported_identity_message,
    _recount_imported_identities,
    _resolve_import_sender,
    _target_room_uuid,
    _upsert_imported_message_source,
)
from app.importers.facebook_messenger.parser import parse_chat_messages, source_hash
from app.models.database import async_session_factory
from app.models.import_tracking import ImportBatch, ImportedMessageSource
from app.models.message import Message
from app.models.photo import Photo


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-folder", required=True)
    parser.add_argument("--room-id", required=True)
    parser.add_argument("--chunk-size", type=int, default=500)
    args = parser.parse_args()

    chat_path = Path(args.chat_folder)
    records = []
    first_message_file = next(iter(sorted(chat_path.glob("message_*.json"))), None)
    source_thread_path = ""
    if first_message_file is not None:
        source_thread_path = json.loads(first_message_file.read_text(encoding="utf-8")).get("thread_path") or ""
    for parsed in parse_chat_messages(chat_path):
        gifs = parsed.raw.get("gifs") or []
        if not gifs:
            continue
        sent_at = datetime.fromtimestamp(parsed.timestamp_ms / 1000, tz=timezone.utc).replace(tzinfo=None)
        for index, item in enumerate(gifs):
            if not isinstance(item, dict) or not item.get("uri"):
                continue
            uri = item["uri"]
            uri_payload = f"gifs:{uri}:{index}"
            record_hash = source_hash(
                source_thread_path=source_thread_path,
                sender_name=parsed.sender_name,
                timestamp_ms=parsed.timestamp_ms,
                content=uri_payload,
                raw=parsed.raw,
            )
            records.append({
                "sender_name": repair_text(parsed.sender_name).strip(),
                "sent_at": sent_at,
                "timestamp_ms": parsed.timestamp_ms,
                "source_thread_path": source_thread_path,
                "source_hash": record_hash,
                "uri": uri,
                "source_file": parsed.source_file.name,
                "keys": sorted(parsed.raw.keys()),
                "reactions": parsed.raw.get("reactions") or [],
            })

    async with async_session_factory() as db:
        room_uuid = await _target_room_uuid(db, args.room_id)
        existing = set()
        for start in range(0, len(records), 10_000):
            hashes = [record["source_hash"] for record in records[start:start + 10_000]]
            rows = await db.execute(
                select(ImportedMessageSource.source_hash).where(
                    ImportedMessageSource.provider == PROVIDER,
                    ImportedMessageSource.source_hash.in_(hashes),
                )
            )
            existing.update(rows.scalars().all())

        batch = ImportBatch(
            provider=PROVIDER,
            source_path=str(chat_path),
            source_thread_path=source_thread_path,
            target_room_id=args.room_id,
            status="running",
            message_count=sum(1 for parsed in parse_chat_messages(chat_path) if parsed.raw.get("gifs")),
            media_count=len(records),
            skipped_count=len(existing),
            errors=[],
        )
        db.add(batch)
        await db.flush()
        batch_id = batch.id
        await db.commit()

        imported = 0
        skipped = len(existing)
        touched_identity_ids: set[uuid.UUID] = set()

        try:
            for start in range(0, len(records), args.chunk_size):
                chunk = records[start:start + args.chunk_size]
                for record in chunk:
                    if record["source_hash"] in existing:
                        continue

                    user, imported_identity = await _resolve_import_sender(db, record["sender_name"], None)
                    db_message = Message(
                        user_session_id=user.session_id,
                        user_id=user.id,
                        imported_identity_id=imported_identity.id,
                        content="\u200b",
                        created_at=record["sent_at"],
                        is_imported=True,
                        room_id=room_uuid,
                    )
                    db.add(db_message)
                    await db.flush()

                    filename = f"missing_gif_{uuid.uuid5(PLACEHOLDER_NAMESPACE, record['source_hash'] + ':missing-gif').hex}.gif"
                    original_filename = Path(record["uri"].split("?", 1)[0]).name[:255] or "missing.gif"
                    photo = Photo(
                        filename=filename,
                        thumbnail_filename=None,
                        original_filename=original_filename,
                        content_type="image/gif",
                        size_bytes=0,
                        file_size_bytes=0,
                        source_type="messenger_import",
                        storage_path="",
                        tags=["imported", "facebook_messenger", "gif", "missing"],
                        uploaded_by_session_id=user.session_id,
                        created_at=record["sent_at"],
                        taken_at=record["sent_at"],
                        room_id=room_uuid,
                        message_id=db_message.id,
                        import_batch_id=batch_id,
                        conversation_id=args.room_id,
                    )
                    db.add(photo)
                    await db.flush()

                    await _upsert_imported_message_source(
                        db,
                        batch_id=batch_id,
                        message_id=db_message.id,
                        record=type("Record", (), {
                            "source_thread_path": record["source_thread_path"],
                            "source_hash": record["source_hash"],
                            "sender_name": record["sender_name"],
                            "sent_at": record["sent_at"],
                            "raw_metadata": {
                                "source_file": record["source_file"],
                                "keys": record["keys"],
                                "media_entries": [{"kind": "gifs", "uri": record["uri"]}],
                                "reactions": record["reactions"],
                                "placeholder": "missing_gif",
                            },
                        })(),
                        target_room_id=args.room_id,
                    )
                    _record_imported_identity_message(imported_identity, record["sent_at"])
                    touched_identity_ids.add(imported_identity.id)
                    imported += 1

                await _recount_imported_identities(db, touched_identity_ids)
                await db.commit()
                print(f"{min(start + len(chunk), len(records))}/{len(records)} imported={imported} skipped={skipped}", flush=True)

            await db.execute(
                update(ImportBatch)
                .where(ImportBatch.id == batch_id)
                .values(
                    status="completed",
                    completed_at=datetime.utcnow(),
                    imported_count=imported,
                    skipped_count=skipped,
                    media_count=len(records),
                    error_count=0,
                    errors=[],
                )
            )
            await db.commit()
            print({"batch_id": batch_id, "imported": imported, "skipped": skipped, "media_count": len(records)})
        except Exception as exc:
            await db.rollback()
            await db.execute(
                update(ImportBatch)
                .where(ImportBatch.id == batch_id)
                .values(
                    status="failed",
                    completed_at=datetime.utcnow(),
                    imported_count=imported,
                    skipped_count=skipped,
                    media_count=len(records),
                    error_count=1,
                    errors=[{"type": "placeholder_backfill_failed", "message": str(exc)}],
                )
            )
            await db.commit()
            raise


if __name__ == "__main__":
    asyncio.run(main())
