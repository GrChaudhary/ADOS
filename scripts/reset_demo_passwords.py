"""
Script to reset all ADOS user login passwords to 'password123'.
"""

import asyncio
from db.engine import async_session_factory
from backend.app.user_store import reset_password, list_users, SEED_ACCOUNTS, create_user


async def main():
    async with async_session_factory() as session:
        users = await list_users(session)
        print("Existing users in Postgres DB:", [u.username for u in users])

        default_pwd = "password123"
        for account in SEED_ACCOUNTS:
            uname = account["username"]
            ok = await reset_password(session, uname, default_pwd)
            if not ok:
                await create_user(
                    session,
                    username=uname,
                    password=default_pwd,
                    display_name=account["display_name"],
                    role=account["role"],
                    approval_limit_usd=account["approval_limit_usd"],
                )
            print(f"✓ Reset user '{uname}' password -> '{default_pwd}'")

        await session.commit()
        print("\nAll demo login passwords have been successfully reset to: password123")


if __name__ == "__main__":
    asyncio.run(main())
