"""
Manual, out-of-band password reset for RBAC accounts (backend/app/user_store.py).

Talks to Postgres directly via db.engine.async_session_factory — deliberately
NOT a wrapper around POST /auth/users/{username}/reset-password. That REST
endpoint is ADMIN-only, which is a chicken-and-egg problem the moment you're
the one locked out (e.g. the original demo passwords, printed once at first
boot and never persisted anywhere in plaintext, are gone): you can't mint an
admin JWT without already having a working admin password. This script needs
nothing but shell access to the machine running Postgres.

Usage:
    python scripts/reset_user_password.py admin
    python scripts/reset_user_password.py admin --password "a specific value"
    python scripts/reset_user_password.py --all-demo-accounts
"""

import argparse
import asyncio
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app import user_store
from db.engine import async_session_factory, engine


async def _reset_one(username: str, password: str) -> bool:
    async with async_session_factory() as session:
        ok = await user_store.reset_password(session, username, password)
        if ok:
            await session.commit()
        return ok


async def _run(args: argparse.Namespace) -> int:
    if args.all_demo_accounts:
        if args.password:
            print("--password isn't allowed with --all-demo-accounts — each account gets its own generated one.", file=sys.stderr)
            return 1
        usernames = [account["username"] for account in user_store.SEED_ACCOUNTS]
    else:
        if not args.username:
            print("Provide a username, or pass --all-demo-accounts.", file=sys.stderr)
            return 1
        usernames = [args.username]

    results: dict[str, str] = {}
    missing: list[str] = []
    for username in usernames:
        password = args.password or secrets.token_urlsafe(9)
        if await _reset_one(username, password):
            results[username] = password
        else:
            missing.append(username)

    if results:
        print("Password reset — save these now, they are never shown again:")
        for username, password in results.items():
            print(f"  {username} / {password}")
    if missing:
        print(f"Username(s) not found, skipped: {', '.join(missing)}", file=sys.stderr)

    await engine.dispose()
    return 1 if missing and not results else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("username", nargs="?", help="Username to reset (omit when using --all-demo-accounts)")
    parser.add_argument("--password", help="Specific new password; omit to generate a random one (recommended)")
    parser.add_argument(
        "--all-demo-accounts", action="store_true",
        help="Reset every seeded demo account (emma, marcus, sophia, auditor, admin) with fresh random passwords",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
