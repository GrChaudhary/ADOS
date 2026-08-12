"""
Real per-user RBAC — replaces the shared-secret bearer token
(SERVICE_AUTH_TOKEN) that used to gate every route identically regardless
of who was calling. Sessions are stateless JWTs: role and approval limit
are baked into the token at login (backend/app/routers/auth.py), so
verifying a request never needs a database round-trip — same reasoning
knowledge/local_llm_client.py etc. use for other "gate on process state,
not a live call" checks in this codebase.

`approved_by` on an incident approval used to be a free-text string the
client supplied — nothing checked it against the caller. Now it's derived
server-side from the verified token via get_current_user(), and the
role/approval_limit_usd on that token is what backend/app/routers/
incidents.py actually authorizes against.
"""

import time
from enum import Enum
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from .config import settings

_JWT_ALGORITHM = "HS256"
_TOKEN_TTL_SECONDS = 12 * 60 * 60  # 12h — long enough for a work session

_bearer_scheme = HTTPBearer(auto_error=False)


class Role(str, Enum):
    MANAGER = "manager"
    EXECUTIVE = "executive"
    ADMIN = "admin"
    AUDITOR = "auditor"


class User(BaseModel):
    """A row of the users table (db/models/users.py, wrapped by
    backend/app/user_store.py). Never carries password_hash past
    user_store.py — that field is verified there and dropped before this
    model is built."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: str = Field(alias="userId")
    username: str
    display_name: str = Field(alias="displayName")
    role: Role
    approval_limit_usd: float = Field(alias="approvalLimitUsd")
    active: bool = True


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user: User) -> str:
    now = int(time.time())
    payload = {
        "sub": user.user_id,
        "username": user.username,
        "displayName": user.display_name,
        "role": user.role.value,
        "approvalLimitUsd": user.approval_limit_usd,
        "active": user.active,
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired session: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return User(
        user_id=payload["sub"],
        username=payload["username"],
        display_name=payload["displayName"],
        role=Role(payload["role"]),
        approval_limit_usd=payload["approvalLimitUsd"],
        active=payload.get("active", True),
    )


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> User:
    """Reads the session JWT from the Authorization header, or a ?token=
    query param for callers that can't set headers — events_stream.py's
    SSE endpoint has that exact constraint today with the old shared
    token, and the frontend's openIncidentEventStream() relies on it."""
    token: Optional[str] = None
    if credentials is not None and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
    elif "token" in request.query_params:
        token = request.query_params["token"]

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = decode_access_token(token)
    if not user.active:
        from .metrics import authorization_denials_total
        authorization_denials_total.labels(reason="inactive_account").inc()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account deactivated")
    return user


def authorize_governance_decision(
    user: "User",
    *,
    policy_tier: int,
    estimated_cost_usd: float = 0.0,
    subject: str = "action",
) -> None:
    """May this user decide this governed action? Raises 403 if not.

    Extracted from backend/app/routers/moa.py, which had the only copy, when
    Prime Agent runtime capability requests needed the same rule. There is one
    implementation deliberately: two would drift, and the cheap direction for
    them to drift is permissive. `moa.py::_authorize_decision` now delegates
    here rather than keeping a parallel copy.

    The rule is unchanged from the MOA path:
      * auditors decide nothing — the role is read-only everywhere;
      * Tier 2 (executive-approval) needs EXECUTIVE or ADMIN;
      * the action's estimated cost must be within the approver's own limit.
    """
    from .metrics import authorization_denials_total

    if user.role == Role.AUDITOR:
        authorization_denials_total.labels(reason="role_readonly").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Auditors have read-only access and cannot decide {subject}s",
        )
    if policy_tier == 2 and user.role not in (Role.EXECUTIVE, Role.ADMIN):
        authorization_denials_total.labels(reason="tier_role_mismatch").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{user.role.value}' cannot decide Tier 2 (executive-approval) {subject}s",
        )
    if user.approval_limit_usd < estimated_cost_usd:
        authorization_denials_total.labels(reason="over_approval_limit").inc()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Approval limit ${user.approval_limit_usd:,.0f} is below this action's "
            f"${estimated_cost_usd:,.0f} estimated cost",
        )


def require_role(*allowed: Role):
    """Dependency factory for endpoints only some roles may call (e.g.
    user management is ADMIN-only). Layers on top of get_current_user
    rather than replacing it, so callers still get 401 (not authenticated)
    vs 403 (authenticated, wrong role) distinctly."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' cannot perform this action",
            )
        return user

    return _check
