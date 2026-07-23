#!/usr/bin/env python3
"""
Extract a labelled inbox conversation from Facebook Messenger export zips.

Scans all .zip files in --source for folders matching messages/inbox/{label}_*,
merges message JSON files across zips (deduplicating by timestamp_ms),
and copies media files to --output.

Usage:
    python fetch.py --source /path/to/export-zips --label example-group --output ../data/example-group
    python fetch.py --source /path/to/export-zips --label example-group --output ../data/example-group --dry-run
    python fetch.py ... --max-messages 10000 --max-photos 50 --max-gifs 50

Labels are the neutral folder prefix before Facebook's generated numeric suffix.
"""

import argparse
import json
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path


MESSAGES_PER_FILE = 10_000


def find_zips(source: Path) -> list[Path]:
    return sorted(source.glob("*.zip"))


SKIP_FOLDERS = {"videos", "audio"}
INBOX_MARKER = "messages/inbox/"


def inbox_rest(name: str) -> str | None:
    """Return path relative to messages/inbox for old and new Meta export layouts."""
    lower = name.lower()
    index = lower.find(INBOX_MARKER)
    if index == -1:
        return None
    return name[index + len(INBOX_MARKER) :]


def collect_labels(zf: zipfile.ZipFile) -> Counter:
    labels: Counter = Counter()
    for name in zf.namelist():
        rest = inbox_rest(name)
        if not rest:
            continue
        label = rest.split("/", 1)[0]
        if label:
            labels[label] += 1
    return labels


def collect_from_zip(zf: zipfile.ZipFile, label: str) -> tuple[list, list]:
    """Return (message_entries, media_entries) for the given label. Videos are skipped."""
    label_prefix = f"{label}_"
    message_entries = []
    media_entries = []

    for name in zf.namelist():
        rest = inbox_rest(name)
        if not rest or not rest.lower().startswith(label_prefix.lower()):
            continue
        rest = rest[rest.index("/") + 1 :] if "/" in rest else ""
        if not rest or rest.endswith("/"):
            continue
        filename = Path(rest).name
        if not filename:
            continue

        parts = Path(rest).parts
        if parts[0] in SKIP_FOLDERS:
            continue

        if len(parts) == 1 and filename.startswith("message_") and filename.endswith(".json"):
            message_entries.append(name)
        else:
            media_entries.append((name, rest))

    return message_entries, media_entries


def merge_messages(all_messages: list[dict]) -> list[dict]:
    seen = {}
    for msg in all_messages:
        ts = msg.get("timestamp_ms")
        sender = msg.get("sender_name", "")
        key = (ts, sender)
        if key not in seen:
            seen[key] = msg
    return sorted(seen.values(), key=lambda m: m.get("timestamp_ms", 0))


def chunk_messages(messages: list[dict], chunk_size: int) -> list[list[dict]]:
    if not messages:
        return []
    return [messages[i : i + chunk_size] for i in range(0, len(messages), chunk_size)]


def write_message_files(chunks: list[list[dict]], output: Path, dry_run: bool, metadata: dict) -> int:
    for i, chunk in enumerate(chunks, 1):
        out_path = output / f"message_{i}.json"
        if dry_run:
            print(f"  [dry-run] would write {out_path} ({len(chunk)} messages)")
        else:
            payload = {**metadata, "messages": chunk}
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return len(chunks)


def main():
    parser = argparse.ArgumentParser(description="Extract labelled Messenger inbox from FB export zips")
    parser.add_argument("--source", required=True, help="Directory containing .zip files")
    parser.add_argument("--label", help="Inbox folder label prefix (e.g. example-group)")
    parser.add_argument("--output", help="Destination directory")
    parser.add_argument("--max-messages", type=int, default=10_000, help="Max messages to extract (most recent)")
    parser.add_argument("--max-photos", type=int, default=50, help="Max photos to extract")
    parser.add_argument("--max-gifs", type=int, default=50, help="Max gifs to extract")
    parser.add_argument("--list-labels", action="store_true", help="List inbox labels found in the export zips")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output) if args.output else None
    label = args.label

    if not source.is_dir():
        print(f"ERROR: --source {source} is not a directory", file=sys.stderr)
        sys.exit(1)

    zips = find_zips(source)
    print(f"Found {len(zips)} zip file(s) in {source}")

    if args.list_labels:
        labels: Counter = Counter()
        skipped = 0
        for zip_path in zips:
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    labels.update(collect_labels(zf))
            except zipfile.BadZipFile:
                print(f"  {zip_path.name}: skipped (not a valid zip)")
                skipped += 1
        print(f"\nInbox labels: {len(labels)} ({skipped} zip(s) skipped)")
        for name, count in labels.most_common():
            print(f"{name}\t{count}")
        return

    if not label or output is None:
        print("ERROR: --label and --output are required unless --list-labels is used", file=sys.stderr)
        sys.exit(1)

    all_messages: list[dict] = []
    chat_metadata: dict = {"participants": [], "title": "", "thread_path": ""}
    # media: relative path -> (zip_path, entry_name) — first seen wins
    media_map: dict[str, tuple[Path, str]] = {}

    skipped = 0
    matched_zips = 0

    for zip_path in zips:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                msg_entries, media_entries = collect_from_zip(zf, label)

                if not msg_entries and not media_entries:
                    continue

                matched_zips += 1
                print(f"  {zip_path.name}: {len(msg_entries)} message file(s), {len(media_entries)} media file(s)")

                for entry in msg_entries:
                    data = json.loads(zf.read(entry))
                    if not chat_metadata["participants"] and data.get("participants"):
                        chat_metadata["participants"] = data["participants"]
                    if not chat_metadata["title"] and data.get("title"):
                        chat_metadata["title"] = data["title"]
                    if not chat_metadata["thread_path"] and data.get("thread_path"):
                        chat_metadata["thread_path"] = data["thread_path"]
                    all_messages.extend(data.get("messages", []))

                for entry_name, rel_path in media_entries:
                    if rel_path not in media_map:
                        media_map[rel_path] = (zip_path, entry_name)

        except zipfile.BadZipFile:
            print(f"  {zip_path.name}: skipped (not a valid zip)")
            skipped += 1

    if matched_zips == 0:
        print(f"\nNo folders matching label '{label}' found in any zip.")
        sys.exit(0)

    merged = merge_messages(all_messages)
    duplicates_dropped = len(all_messages) - len(merged)
    if not merged:
        print("\nWARNING: No message JSON files were found for this label. This export appears to contain media only.")

    # Take most recent N messages
    if len(merged) > args.max_messages:
        merged = merged[-args.max_messages:]

    chunks = chunk_messages(merged, MESSAGES_PER_FILE)

    # Apply per-folder media limits (videos already excluded at collection time)
    folder_limits = {"photos": args.max_photos, "gifs": args.max_gifs}
    folder_counts: dict[str, int] = {}
    limited_media: dict[str, tuple[Path, str]] = {}
    media_capped = 0
    for rel_path, value in media_map.items():
        folder = Path(rel_path).parts[0] if len(Path(rel_path).parts) > 1 else ""
        limit = folder_limits.get(folder)
        if limit is not None:
            count = folder_counts.get(folder, 0)
            if count >= limit:
                media_capped += 1
                continue
            folder_counts[folder] = count + 1
        limited_media[rel_path] = value

    print(f"\nMessages: {len(all_messages)} collected, {duplicates_dropped} duplicates dropped → {len(merged)} kept (limit: {args.max_messages})")
    print(f"Media: {len(limited_media)} kept, {media_capped} capped by limit (videos skipped)")

    if not args.dry_run:
        output.mkdir(parents=True, exist_ok=True)
        # Remove stale message files from any previous run so the importer
        # doesn't pick up old chunks that exceed our current limit.
        for stale in output.glob("message_*.json"):
            stale.unlink()

    # Write message JSON files
    n_files = write_message_files(chunks, output, args.dry_run, chat_metadata)

    # Extract media
    media_written = 0
    media_skipped = 0
    for rel_path, (zip_path, entry_name) in limited_media.items():
        dest = output / rel_path
        if args.dry_run:
            print(f"  [dry-run] would extract {rel_path}")
            media_written += 1
            continue
        if dest.exists():
            media_skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            dest.write_bytes(zf.read(entry_name))
        media_written += 1

    print(f"\nDone.")
    print(f"  Zips scanned: {len(zips)}  ({skipped} skipped, {matched_zips} matched)")
    print(f"  Message files written: {n_files}")
    print(f"  Media extracted: {media_written}  ({media_skipped} already existed)")
    if not args.dry_run:
        print(f"  Output: {output.resolve()}")


if __name__ == "__main__":
    main()
