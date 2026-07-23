"""Developer CLI for importing Facebook Messenger exports into Friend Hub."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
from typing import Any

import asyncpg

from app.config import resolve_repo_path

from .importer import dry_run_chat, import_chat, resolve_chat_dir
from .sender_map import load_sender_map


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="friend-hub-messenger-import")
    parser.add_argument("--export-root", default=os.getenv("MESSENGER_EXPORT_ROOT"))
    parser.add_argument("--chat-folder", default=os.getenv("MESSENGER_CHAT_FOLDER"))
    parser.add_argument("--room-id", default=os.getenv("MESSENGER_ROOM_ID"))
    parser.add_argument("--sender-map", default=os.getenv("MESSENGER_SENDER_MAP"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose-errors", action="store_true", help="Print the full per-message import error list")
    parser.add_argument("--chunk-size", type=int, default=500)

    args = parser.parse_args(argv)
    _require_arg(args.export_root, "--export-root or MESSENGER_EXPORT_ROOT")
    _require_arg(args.chat_folder, "--chat-folder or MESSENGER_CHAT_FOLDER")
    _require_arg(args.room_id, "--room-id or MESSENGER_ROOM_ID")

    export_root = _resolve_path(args.export_root)
    sender_map_path = _resolve_path(args.sender_map) if args.sender_map else None
    sender_map = load_sender_map(sender_map_path)

    result = asyncio.run(_run(args, export_root, sender_map))
    _print_json(_output_payload(result, verbose_errors=args.verbose_errors))
    return 0 if result.get("status") != "failed" else 1


async def _run(args, export_root: Path, sender_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    await _ensure_import_tracking_schema()

    from app.models.database import async_session_factory

    async with async_session_factory() as db:
        if args.dry_run:
            summary = await dry_run_chat(
                export_root=export_root,
                chat_folder=args.chat_folder,
                target_room_id=args.room_id,
                db=db,
                sender_map=sender_map,
            )
            return {"dry_run": True, **summary.to_dict()}

        chat_dir = resolve_chat_dir(export_root, args.chat_folder)
        summary = await import_chat(
            chat_dir,
            db,
            chunk_size=args.chunk_size,
            target_room_id=args.room_id,
            sender_map=sender_map,
            export_root=export_root,
        )
        return {"dry_run": False, **summary.__dict__}


async def _ensure_import_tracking_schema() -> None:
    from app.config import get_settings

    settings = get_settings()
    migration_path = Path(__file__).resolve().parents[3] / "migrations" / "017_add_import_tracking.sql"
    sql = migration_path.read_text(encoding="utf-8")
    conn = await asyncpg.connect(
        host=settings.database_host,
        port=settings.database_port,
        user=settings.database_user,
        password=settings.database_password,
        database=settings.database_name,
        timeout=10,
    )
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def _resolve_path(value: str | None) -> Path:
    resolved = resolve_repo_path(value)
    if resolved is None:
        raise SystemExit("Path value is required")
    return resolved


def _require_arg(value: str | None, label: str) -> None:
    if not value:
        raise SystemExit(f"Missing required {label}")


def _output_payload(payload: dict[str, Any], *, verbose_errors: bool) -> dict[str, Any]:
    output = dict(payload)
    errors = list(output.get("errors") or [])
    if not errors:
        return output

    output["error_summary"] = dict(sorted(Counter(_error_type(error) for error in errors).items()))
    if not verbose_errors:
        output.pop("errors", None)
        output["error_details_omitted"] = len(errors)
    return output


def _error_type(error: Any) -> str:
    if isinstance(error, dict) and error.get("type"):
        return str(error["type"])
    return "unknown"


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    raise SystemExit(main())
