import argparse
import asyncio

from app.domains.auth.service import AuthService
from app.models.database import async_session_factory
from app.models.message import UserRole


def parse_args():
    parser = argparse.ArgumentParser(description="Create the first Friend Hub admin invite.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    return parser.parse_args()


async def main():
    args = parse_args()
    async with async_session_factory() as db:
        service = AuthService(db)
        active_admins = await service.repository.count_active_admins()
        if active_admins:
            raise SystemExit("Refusing to bootstrap: an active admin already exists.")
        user, invite_code, error = await service.create_admin_user(
            username=args.username,
            display_name=args.display_name,
            role=UserRole.admin.value,
        )
        if error or not user or not invite_code:
            raise SystemExit(error or "Could not create admin invite.")
        print(f"Admin user: {user.username}")
        print(f"Invite code: {invite_code}")
        print("This code will only be shown once. Copy it now.")


if __name__ == "__main__":
    asyncio.run(main())
