"""Run one or more SQL migration files against the local database."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

import asyncpg
from app.config import get_settings

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def main(files: list[str]) -> None:
    settings = get_settings()
    conn = await asyncpg.connect(
        host=settings.database_host,
        port=settings.database_port,
        user=settings.database_user,
        password=settings.database_password,
        database=settings.database_name,
    )

    try:
        for f in files:
            path = Path(f) if Path(f).is_absolute() else MIGRATIONS_DIR / f
            if not path.exists():
                print(f"ERROR: file not found: {path}", file=sys.stderr)
                sys.exit(1)
            sql = path.read_text()
            print(f"Running {path.name}…")
            await conn.execute(sql)
            print(f"  ✓ done")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+", help="Migration file name(s) or absolute paths")
    args = parser.parse_args()
    asyncio.run(main(args.files))
