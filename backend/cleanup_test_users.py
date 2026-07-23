import argparse
import asyncio
import uuid
from datetime import datetime

from sqlalchemy import select, update

from app.models.database import async_session_factory
from app.models.message import User, UserRole
from app.models.user_session import UserSession


def parse_args():
    parser = argparse.ArgumentParser(description="Deactivate old Friend Hub test users. Dry run by default.")
    parser.add_argument("--apply", action="store_true", help="Actually deactivate users and revoke sessions.")
    parser.add_argument("--keep", action="append", default=[], help="Username or user id to keep. Can be repeated.")
    return parser.parse_args()


async def main():
    args = parse_args()
    keep = {value.strip().lower() for value in args.keep if value.strip()}
    async with async_session_factory() as db:
        result = await db.execute(select(User).order_by(User.created_at))
        users = list(result.scalars().all())
        active_admins = [u for u in users if u.is_active and u.role in {UserRole.owner, UserRole.admin}]
        if not active_admins:
            raise SystemExit("Refusing to continue: no active admin exists.")

        targets = []
        for user in users:
            identifiers = {str(user.id).lower(), str(user.session_id).lower(), (user.username or "").lower()}
            if identifiers & keep:
                continue
            if user.is_active and user.role not in {UserRole.owner, UserRole.admin}:
                targets.append(user)

        print("Users that would be deactivated:")
        for user in targets:
            print(f"- {user.username} ({user.id})")

        if not args.apply:
            print("Dry run only. Re-run with --apply to deactivate these users.")
            return

        now = datetime.utcnow()
        for user in targets:
            user.is_active = False
            user.updated_at = now
            await db.execute(
                update(UserSession)
                .where(UserSession.user_id == user.id)
                .where(UserSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
        await db.commit()
        print(f"Deactivated {len(targets)} users and revoked their sessions.")


if __name__ == "__main__":
    asyncio.run(main())
