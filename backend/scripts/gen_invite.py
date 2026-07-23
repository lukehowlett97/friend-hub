"""Generate and persist a fresh admin invite code for a given username."""

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

import asyncpg
from app.config import get_settings
from app.domains.auth.tokens import generate_invite_code, hash_secret

INVITE_DAYS = 7


async def main(username: str) -> None:
    settings = get_settings()
    pool = await asyncpg.create_pool(
        host=settings.database_host,
        port=settings.database_port,
        user=settings.database_user,
        password=settings.database_password,
        database=settings.database_name,
    )

    code = generate_invite_code()
    code_hash = hash_secret(code)
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE users
               SET invite_code_hash       = $1,
                   invite_code_used_at    = NULL,
                   invite_code_expires_at = $2,
                   role                   = 'admin',
                   updated_at             = NOW()
             WHERE LOWER(username) = LOWER($3)
         RETURNING session_id, username, display_name
            """,
            code_hash,
            expires_at,
            username,
        )

        if not row:
            answer = input(f"No user '{username}' found. Create them? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted.")
                await pool.close()
                sys.exit(1)

            row = await conn.fetchrow(
                """
                INSERT INTO users (username, nickname, display_name, role, invite_code_hash, invite_code_expires_at)
                VALUES ($1, $2, $2, 'admin', $3, $4)
                RETURNING session_id, username, display_name
                """,
                username,
                username,
                code_hash,
                expires_at,
            )

        await conn.execute(
            """
            INSERT INTO group_members (user_session_id, role)
            VALUES ($1, 'admin')
            ON CONFLICT (user_session_id)
            DO UPDATE SET role = 'admin'
            """,
            row["session_id"],
        )

    await pool.close()

    print(f"User     : {row['display_name']} (@{row['username']})")
    print(f"Code     : {code}")
    print(f"Expires  : {expires_at.strftime('%Y-%m-%d %H:%M UTC')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("username", help="Username to generate an invite code for")
    args = parser.parse_args()
    asyncio.run(main(args.username))
