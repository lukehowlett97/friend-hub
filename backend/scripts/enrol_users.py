"""Enrol all active users into the default 'main' room."""

import asyncio
import sys
import uuid

sys.path.insert(0, ".")

import asyncpg
from app.config import get_settings

MAIN_ROOM_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def main() -> None:
    settings = get_settings()
    pool = await asyncpg.create_pool(
        host=settings.database_host,
        port=settings.database_port,
        user=settings.database_user,
        password=settings.database_password,
        database=settings.database_name,
    )

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            INSERT INTO room_memberships (room_id, user_id, role)
            SELECT
                $1,
                id,
                CASE WHEN role IN ('owner', 'admin') THEN 'admin' ELSE 'member' END
            FROM users
            WHERE is_active = TRUE AND id IS NOT NULL
            ON CONFLICT (room_id, user_id) DO NOTHING
            """,
            MAIN_ROOM_ID,
        )
        count = int(result.split()[-1])

        await conn.execute(
            """
            UPDATE room_memberships SET role = 'owner'
            WHERE room_id = $1
              AND user_id = (
                  SELECT id FROM users WHERE role = 'owner' AND is_active = TRUE
                  ORDER BY created_at ASC LIMIT 1
              )
            """,
            MAIN_ROOM_ID,
        )

    await pool.close()
    print(f"Enrolled {count} user(s) into the main room.")


if __name__ == "__main__":
    asyncio.run(main())
