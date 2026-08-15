"""
P17 — resolves the active tenant for a request from AUTHENTICATED
IDENTITY (the JWT's `tenantIds` claim, itself populated only at login from
`tenant_memberships` — see backend/app/user_store.py::verify_login), never
from a caller-supplied body field. See db/tenancy.py for the ORM-level
enforcement this feeds, and
docs/prime-agent-integration/28-multi-tenancy-and-tenant-isolation.md for
the full design.

ACTIVE TENANT SELECTION
-------------------------
A user with exactly one membership (every seeded account today) needs no
extra step — that membership is the active tenant automatically. A user
in more than one tenant MUST send `X-Tenant-Id`, cross-checked against
their own JWT-verified membership set — supplying someone else's tenant
id is refused with the same 403 regardless of whether that tenant exists,
so this endpoint can never be used to enumerate real tenant ids.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator, FrozenSet

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel

from db.tenancy import use_tenant

from .rbac import User, get_current_user

TENANT_HEADER = "X-Tenant-Id"


class TenantContext(BaseModel):
    tenant_id: uuid.UUID
    memberships: FrozenSet[uuid.UUID]


async def get_tenant_context(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> AsyncIterator[TenantContext]:
    try:
        memberships = frozenset(uuid.UUID(t) for t in current_user.tenant_ids)
    except ValueError:
        # A malformed claim means the token itself is not trustworthy for
        # tenant purposes -- refuse rather than guess which entries are real.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="session token carries a malformed tenant membership claim; please log in again",
        )

    header_value = request.headers.get(TENANT_HEADER)
    if header_value:
        try:
            requested = uuid.UUID(header_value)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"malformed {TENANT_HEADER} header")
        if requested not in memberships:
            raise HTTPException(status_code=403, detail="not a member of the requested tenant")
        active = requested
    elif len(memberships) == 1:
        active = next(iter(memberships))
    elif not memberships:
        raise HTTPException(status_code=403, detail="user has no tenant memberships")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"user belongs to multiple tenants; specify the {TENANT_HEADER} header",
        )

    with use_tenant(active):
        yield TenantContext(tenant_id=active, memberships=memberships)
