"""
User persistence for RBAC (backend/app/rbac.py). Wraps knowledge/
cloudant_client.py's new save_user/get_user_by_username/list_users when
Cloudant is configured, and falls back to an in-memory dict otherwise —
same graceful-degrade convention as knowledge/nlu_client.py,
knowledge/tts_client.py, and knowledge/local_llm_client.py: real when
configured, honestly degraded (never fabricated) when not.

Seeded accounts mirror the 4 personas the frontend already had
(frontend-next/src/lib/usePersona.ts) plus a new admin account for user
management, which none of the 4 covered.
"""

import secrets
import uuid
from typing import Any, Dict, List, Optional

from knowledge.cloudant_client import cloudant_db

from .rbac import Role, User, hash_password, verify_password

# username -> user doc (includes password_hash) — only used when Cloudant
# isn't configured. Module-level so it survives across requests within
# one process, same lifetime as cloudant_db's in-memory client.
_IN_MEMORY_USERS: Dict[str, Dict[str, Any]] = {}

SEED_ACCOUNTS = [
    {"username": "emma", "display_name": "Emma Vance", "role": Role.MANAGER, "approval_limit_usd": 250_000.0},
    {"username": "marcus", "display_name": "Marcus Vance", "role": Role.MANAGER, "approval_limit_usd": 500_000.0},
    {"username": "sophia", "display_name": "Sophia Vance", "role": Role.EXECUTIVE, "approval_limit_usd": 5_000_000.0},
    {"username": "auditor", "display_name": "Compliance Auditor", "role": Role.AUDITOR, "approval_limit_usd": 0.0},
    # A large finite ceiling, not float("inf") — Infinity isn't valid JSON
    # and would break JWT/Cloudant document encoding.
    {"username": "admin", "display_name": "System Administrator", "role": Role.ADMIN, "approval_limit_usd": 1_000_000_000.0},
]


def _doc_to_user(doc: Dict[str, Any]) -> User:
    return User(
        user_id=doc.get("userId") or doc.get("user_id"),
        username=doc["username"],
        display_name=doc.get("displayName") or doc.get("display_name"),
        role=Role(doc["role"]),
        approval_limit_usd=doc.get("approvalLimitUsd") if doc.get("approvalLimitUsd") is not None else doc.get("approval_limit_usd"),
        active=doc.get("active", True),
    )


def _get_by_username(username: str) -> Optional[Dict[str, Any]]:
    if cloudant_db.is_configured():
        return cloudant_db.get_user_by_username(username)
    return _IN_MEMORY_USERS.get(username)


def _save(doc: Dict[str, Any]) -> None:
    if cloudant_db.is_configured():
        cloudant_db.save_user(doc)
    else:
        _IN_MEMORY_USERS[doc["username"]] = doc


def _list_all() -> List[Dict[str, Any]]:
    if cloudant_db.is_configured():
        return cloudant_db.list_users()
    return list(_IN_MEMORY_USERS.values())


def create_user(username: str, password: str, display_name: str, role: Role, approval_limit_usd: float) -> User:
    doc = {
        "userId": str(uuid.uuid4()),
        "username": username,
        "displayName": display_name,
        "role": role.value,
        "approvalLimitUsd": approval_limit_usd,
        "passwordHash": hash_password(password),
        "active": True,
    }
    _save(doc)
    return _doc_to_user(doc)


def username_exists(username: str) -> bool:
    return _get_by_username(username) is not None


def reset_password(username: str, new_password: str) -> bool:
    """Updates an existing user's password in place. Deliberately not
    create_user() called again — that mints a fresh userId every time, so
    for the Cloudant-backed store (which upserts by _id == userId) it
    would create a second document for the same username rather than
    updating the original. Returns False if the username doesn't exist."""
    doc = _get_by_username(username)
    if doc is None:
        return False
    doc = dict(doc)
    doc["passwordHash"] = hash_password(new_password)
    doc.pop("password_hash", None)  # legacy snake_case key, if present
    _save(doc)
    return True


def verify_login(username: str, password: str) -> Optional[User]:
    doc = _get_by_username(username)
    if not doc or not doc.get("active", True):
        return None
    if not verify_password(password, doc.get("passwordHash") or doc.get("password_hash") or ""):
        return None
    return _doc_to_user(doc)


def list_users() -> List[User]:
    return [_doc_to_user(doc) for doc in _list_all()]


def bootstrap_users() -> Optional[Dict[str, str]]:
    """Seeds SEED_ACCOUNTS with random passwords only if the store is
    currently empty (never overwrites/resets existing accounts — an admin
    may have already changed a password). Returns the generated
    {username: password} map so main.py can print it once, or None if
    seeding was skipped because accounts already exist."""
    if _list_all():
        return None

    generated: Dict[str, str] = {}
    for account in SEED_ACCOUNTS:
        password = secrets.token_urlsafe(9)
        generated[account["username"]] = password
        create_user(
            username=account["username"],
            password=password,
            display_name=account["display_name"],
            role=account["role"],
            approval_limit_usd=account["approval_limit_usd"],
        )
    return generated
