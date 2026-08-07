"""
User persistence for RBAC (backend/app/rbac.py). Postgres-backed via
db/models/users.py, request-scoped session — db/session.py's
get_db_session() FastAPI dependency, the pattern documented there for
plain-CRUD routers with no long-lived singleton. Replaces the old
Cloudant-or-in-memory graceful-degrade split: Postgres is required
application infrastructure now (main.py's lifespan fails fast at startup
if it's unreachable), so there's no "not configured" case left to fall
back for.

Seeded accounts mirror the 4 personas the frontend already had
(frontend-next/src/lib/usePersona.ts) plus a new admin account for user
management, which none of the 4 covered.
"""

import secrets
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.users import UserRow

from .rbac import Role, User, hash_password, verify_password

SEED_ACCOUNTS = [
    {"username": "emma", "display_name": "Emma Vance", "role": Role.MANAGER, "approval_limit_usd": 250_000.0},
    {"username": "marcus", "display_name": "Marcus Vance", "role": Role.MANAGER, "approval_limit_usd": 500_000.0},
    {"username": "sophia", "display_name": "Sophia Vance", "role": Role.EXECUTIVE, "approval_limit_usd": 5_000_000.0},
    {"username": "auditor", "display_name": "Compliance Auditor", "role": Role.AUDITOR, "approval_limit_usd": 0.0},
    # A large finite ceiling, not float("inf") — Infinity isn't valid JSON
    # and would break JWT encoding.
    {"username": "admin", "display_name": "System Administrator", "role": Role.ADMIN, "approval_limit_usd": 1_000_000_000.0},
]


def _row_to_user(row: UserRow) -> User:
    return User(
        user_id=str(row.user_id),
        username=row.username,
        display_name=row.display_name,
        role=Role(row.role),
        approval_limit_usd=row.approval_limit_usd,
        active=row.active,
    )


async def _get_by_username(session: AsyncSession, username: str) -> Optional[UserRow]:
    return (await session.execute(select(UserRow).where(UserRow.username == username))).scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    username: str,
    password: str,
    display_name: str,
    role: Role,
    approval_limit_usd: float,
) -> User:
    row = UserRow(
        username=username,
        display_name=display_name,
        role=role.value,
        approval_limit_usd=approval_limit_usd,
        password_hash=hash_password(password),
    )
    session.add(row)
    await session.flush()  # populate row.user_id (Python-side default) before we read it below
    return _row_to_user(row)


async def username_exists(session: AsyncSession, username: str) -> bool:
    return await _get_by_username(session, username) is not None


async def reset_password(session: AsyncSession, username: str, new_password: str) -> bool:
    """Updates an existing user's password in place, preserving user_id —
    returns False if the username doesn't exist."""
    row = await _get_by_username(session, username)
    if row is None:
        return False
    row.password_hash = hash_password(new_password)
    return True


async def verify_login(session: AsyncSession, username: str, password: str) -> Optional[User]:
    row = await _get_by_username(session, username)
    if row is None or not row.active:
        return None
    if not verify_password(password, row.password_hash):
        return None
    return _row_to_user(row)


async def list_users(session: AsyncSession) -> List[User]:
    rows = (await session.execute(select(UserRow))).scalars().all()
    return [_row_to_user(row) for row in rows]


async def bootstrap_users(session: AsyncSession) -> Optional[Dict[str, str]]:
    """Seeds SEED_ACCOUNTS with random passwords only if the store is
    currently empty (never overwrites/resets existing accounts — an admin
    may have already changed a password). Returns the generated
    {username: password} map so main.py can print it once, or None if
    seeding was skipped because accounts already exist."""
    existing = (await session.execute(select(UserRow.user_id).limit(1))).first()
    if existing is not None:
        return None

    generated: Dict[str, str] = {}
    for account in SEED_ACCOUNTS:
        password = secrets.token_urlsafe(9)
        generated[account["username"]] = password
        await create_user(
            session,
            username=account["username"],
            password=password,
            display_name=account["display_name"],
            role=account["role"],
            approval_limit_usd=account["approval_limit_usd"],
        )
    return generated
