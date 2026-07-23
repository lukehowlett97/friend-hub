"""
Room management CLI.

Commands:
  create-room   --slug SLUG --name NAME
  create-admin  --username USER --room-slug SLUG
  add-member    --username USER --room-slug SLUG [--role member|admin|owner]
  list-rooms
  list-members  --room-slug SLUG
  gen-invite    --room-slug SLUG [--max-uses N] [--days N]

Examples:
  python scripts/manage_room.py create-room --slug gc-plus --name "GC+"
  python scripts/manage_room.py create-admin --username alice --room-slug gc-plus
  python scripts/manage_room.py gen-invite --room-slug gc-plus
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, ".")

import asyncpg
from app.config import get_settings
from app.domains.auth.tokens import generate_invite_code, hash_secret

INVITE_DAYS = 7


async def get_pool() -> asyncpg.Pool:
    s = get_settings()
    return await asyncpg.create_pool(
        host=s.database_host,
        port=s.database_port,
        user=s.database_user,
        password=s.database_password,
        database=s.database_name,
    )


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_room(conn: asyncpg.Connection, slug: str) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT id, slug, name, status FROM rooms WHERE slug = $1", slug)


async def _get_user(conn: asyncpg.Connection, username: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, session_id, username, nickname, role FROM users WHERE LOWER(username) = LOWER($1) AND is_active = TRUE",
        username,
    )


async def _enrol_in_room(conn: asyncpg.Connection, room_id: uuid.UUID, user_id: uuid.UUID, role: str) -> bool:
    result = await conn.execute(
        """
        INSERT INTO room_memberships (room_id, user_id, role)
        VALUES ($1, $2, $3)
        ON CONFLICT (room_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """,
        room_id, user_id, role,
    )
    return True


# ── Commands ─────────────────────────────────────────────────────────────────

async def cmd_create_room(args: argparse.Namespace) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await _get_room(conn, args.slug)
        if existing:
            print(f"Room '{args.slug}' already exists (id={existing['id']})")
            await pool.close()
            return

        room_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO rooms (id, slug, name, status)
            VALUES ($1, $2, $3, 'active')
            """,
            room_id, args.slug, args.name,
        )
        await conn.execute(
            "INSERT INTO room_settings (room_id) VALUES ($1) ON CONFLICT DO NOTHING",
            room_id,
        )

    await pool.close()
    print(f"Created room  : {args.name}")
    print(f"Slug          : {args.slug}")
    print(f"ID            : {room_id}")
    print()
    print(f"Next step — create an owner:")
    print(f"  python scripts/manage_room.py create-admin --username <user> --room-slug {args.slug}")


async def cmd_create_admin(args: argparse.Namespace) -> None:
    pool = await get_pool()

    code = generate_invite_code()
    code_hash = hash_secret(code)
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)

    async with pool.acquire() as conn:
        room = await _get_room(conn, args.room_slug)
        if not room:
            print(f"Error: room '{args.room_slug}' not found.")
            await pool.close()
            sys.exit(1)

        user = await _get_user(conn, args.username)

        if user:
            # Refresh invite code on existing user
            await conn.execute(
                """
                UPDATE users
                   SET invite_code_hash       = $1,
                       invite_code_used_at    = NULL,
                       invite_code_expires_at = $2,
                       updated_at             = NOW()
                 WHERE LOWER(username) = LOWER($3)
                """,
                code_hash, expires_at, args.username,
            )
            user_id = user["id"]
            nickname = user["nickname"]
        else:
            # Create new user
            answer = input(f"User '{args.username}' not found. Create them? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted.")
                await pool.close()
                sys.exit(1)

            user_id = uuid.uuid4()
            session_id = uuid.uuid4()
            nickname = args.username
            await conn.execute(
                """
                INSERT INTO users (id, session_id, username, nickname, display_name, role,
                                   invite_code_hash, invite_code_expires_at)
                VALUES ($1, $2, $3, $4, $4, 'admin', $5, $6)
                """,
                user_id, session_id, args.username, nickname, code_hash, expires_at,
            )

        role = args.role or "owner"
        await _enrol_in_room(conn, room["id"], user_id, role)

    await pool.close()
    print(f"User          : {nickname} (@{args.username})")
    print(f"Room          : {room['name']} ({args.room_slug})")
    print(f"Room role     : {role}")
    print(f"Invite code   : {code}")
    print(f"Expires       : {expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print()
    print("Share the invite code with this user — they use it to log in.")


async def cmd_add_member(args: argparse.Namespace) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        room = await _get_room(conn, args.room_slug)
        if not room:
            print(f"Error: room '{args.room_slug}' not found.")
            await pool.close()
            sys.exit(1)

        user = await _get_user(conn, args.username)
        if not user:
            print(f"Error: user '{args.username}' not found or inactive.")
            await pool.close()
            sys.exit(1)

        role = args.role or "member"
        await _enrol_in_room(conn, room["id"], user["id"], role)

    await pool.close()
    print(f"Added @{args.username} to '{args.room_slug}' as {role}.")


async def cmd_list_rooms(args: argparse.Namespace) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.id, r.slug, r.name, r.status,
                   COUNT(rm.user_id) AS member_count
              FROM rooms r
              LEFT JOIN room_memberships rm ON rm.room_id = r.id
             GROUP BY r.id
             ORDER BY r.created_at
            """
        )

    await pool.close()
    if not rows:
        print("No rooms found.")
        return

    print(f"{'Slug':<20} {'Name':<30} {'Status':<12} {'Members'}")
    print("-" * 72)
    for row in rows:
        print(f"{row['slug']:<20} {row['name']:<30} {row['status']:<12} {row['member_count']}")


async def cmd_list_members(args: argparse.Namespace) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        room = await _get_room(conn, args.room_slug)
        if not room:
            print(f"Error: room '{args.room_slug}' not found.")
            await pool.close()
            sys.exit(1)

        rows = await conn.fetch(
            """
            SELECT u.username, u.nickname, rm.role, rm.joined_at
              FROM room_memberships rm
              JOIN users u ON u.id = rm.user_id
             WHERE rm.room_id = $1
             ORDER BY rm.role, u.nickname
            """,
            room["id"],
        )

    await pool.close()
    print(f"Members of '{args.room_slug}' ({room['name']}):\n")
    print(f"{'Username':<20} {'Nickname':<24} {'Role':<10} Joined")
    print("-" * 72)
    for row in rows:
        joined = row["joined_at"].strftime("%Y-%m-%d") if row["joined_at"] else "—"
        print(f"{(row['username'] or '—'):<20} {row['nickname']:<24} {row['role']:<10} {joined}")


async def cmd_gen_invite(args: argparse.Namespace) -> None:
    """Generate a room invite link that anyone can use to join."""
    pool = await get_pool()

    code = secrets.token_urlsafe(16)
    max_uses = args.max_uses or 1
    days = args.days or INVITE_DAYS
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)

    async with pool.acquire() as conn:
        room = await _get_room(conn, args.room_slug)
        if not room:
            print(f"Error: room '{args.room_slug}' not found.")
            await pool.close()
            sys.exit(1)

        await conn.execute(
            """
            INSERT INTO room_invites (room_id, code, max_uses, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            room["id"], code, max_uses, expires_at,
        )

    await pool.close()
    print(f"Room          : {room['name']} ({args.room_slug})")
    print(f"Invite code   : {code}")
    print(f"Max uses      : {max_uses}")
    print(f"Expires       : {expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
    print()
    print(f"Share this join link: /join/{code}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="manage_room", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-room", help="Create a new room")
    p.add_argument("--slug", required=True, help="Short URL-safe identifier, e.g. gc-plus")
    p.add_argument("--name", required=True, help="Display name, e.g. 'GC+'")

    p = sub.add_parser("create-admin", help="Create or refresh an owner/admin account for a room")
    p.add_argument("--username", required=True)
    p.add_argument("--room-slug", required=True)
    p.add_argument("--role", choices=["owner", "admin", "member"], default="owner")

    p = sub.add_parser("add-member", help="Add an existing user to a room")
    p.add_argument("--username", required=True)
    p.add_argument("--room-slug", required=True)
    p.add_argument("--role", choices=["owner", "admin", "member"], default="member")

    p = sub.add_parser("list-rooms", help="List all rooms")

    p = sub.add_parser("list-members", help="List members of a room")
    p.add_argument("--room-slug", required=True)

    p = sub.add_parser("gen-invite", help="Generate a room invite code")
    p.add_argument("--room-slug", required=True)
    p.add_argument("--max-uses", type=int, default=1, help="How many times the code can be used (default 1)")
    p.add_argument("--days", type=int, default=INVITE_DAYS, help="Days until expiry (default 7)")

    args = parser.parse_args(argv)

    commands = {
        "create-room":   cmd_create_room,
        "create-admin":  cmd_create_admin,
        "add-member":    cmd_add_member,
        "list-rooms":    cmd_list_rooms,
        "list-members":  cmd_list_members,
        "gen-invite":    cmd_gen_invite,
    }

    asyncio.run(commands[args.command](args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
