"""
P17 — the mechanism that makes cross-tenant access impossible through the
normal application APIs, rather than relying on every call site to
remember a `WHERE tenant_id = ...` clause. See
docs/prime-agent-integration/28-multi-tenancy-and-tenant-isolation.md for
the full design and the library evaluation that led here (none of the five
candidates fit a FastAPI/SQLAlchemy/Postgres app without either the wrong
framework or an immature, invasive dependency).

THE MECHANISM
--------------
A single SQLAlchemy `do_orm_execute` event, registered once at import time
on the sync `Session` class (this is the documented way to hook async
sessions too — `AsyncSession` delegates statement execution to an internal
sync `Session`, and the event fires for it; verified against this
project's real Postgres, not assumed). On every ORM SELECT/UPDATE/DELETE
against a tenant-scoped model, it injects a `with_loader_criteria` filter
matching the CURRENT tenant context — for every existing call site, with
zero changes to how routers already construct queries.

Tenant context lives in a `contextvars.ContextVar`, not a module-global or
request-object attribute. This matters under real concurrency: FastAPI/
Starlette runs each request in its own asyncio Task, and `contextvars`
gives each Task its own copy-on-write view — a `.set()` inside one
request's task is invisible to a concurrent sibling request's task,
verified against real Postgres with genuinely concurrent `asyncio.gather`
requests carrying different tenants (see the P17 report's live-evidence
section; the same property `orchestrate/runtime/admission_control.py`
already relies on for its own per-instance state, just applied here to a
context, not an object).

FAIL CLOSED, NOT FAIL OPEN
----------------------------
No tenant context set at all (`current_tenant.get() is None`) filters a
tenant-scoped query to ZERO rows, not all rows. A code path that forgot to
resolve a tenant fails loudly and immediately (empty result / 404), never
silently leaks another tenant's data. The ONE way to see across tenants is
the explicit `use_all_tenants()` context manager below — used only by code
whose authorization already comes from something narrower and stronger
than tenant membership (a possessed session token, or a background job
whose job *is* to scan every tenant) — see each call site's own comment
for why that's safe there.
"""

from __future__ import annotations

import contextvars
import uuid
from contextlib import asynccontextmanager, contextmanager
from typing import Iterator, Optional, Union

from sqlalchemy import false as sql_false
from sqlalchemy.orm import Session, with_loader_criteria

from db.models.mission import CapabilityRequestRow, MissionRow, RuntimeSessionRow
from db.models.tenant import DEFAULT_TENANT_ID  # noqa: F401 -- re-exported for callers

#: Every ORM model a query must be tenant-filtered against. Deliberately an
#: explicit tuple, not a mixin-detection trick — adding a new tenant-owned
#: table means a one-line, reviewable addition here, not silent inclusion
#: by inheritance.
TENANT_SCOPED_MODELS = (MissionRow, RuntimeSessionRow, CapabilityRequestRow)


class _AllTenants:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "ALL_TENANTS"


#: Sentinel distinct from `None` — `None` means "nobody resolved a tenant
#: context" (fail closed); this means "this code path is deliberately
#: cross-tenant" (explicit, reviewed opt-out).
ALL_TENANTS = _AllTenants()

current_tenant: contextvars.ContextVar[Optional[Union[uuid.UUID, _AllTenants]]] = (
    contextvars.ContextVar("ados_current_tenant", default=None)
)


@contextmanager
def use_tenant(tenant_id: uuid.UUID) -> Iterator[None]:
    """Scope every tenant-owned ORM query inside this block to exactly one
    tenant. Used by backend/app/tenancy.py's request-scoped dependency, and
    directly by tests/scripts that need a specific tenant's view."""
    token = current_tenant.set(tenant_id)
    try:
        yield
    finally:
        current_tenant.reset(token)


@contextmanager
def use_all_tenants() -> Iterator[None]:
    """The explicit, reviewed escape hatch. Only for code whose real
    authorization boundary is something other than tenant membership:

    - backend/app/mcp_gateway.py: the runtime holds a possessed, opaque,
      per-session bearer token (identity-only, unforgeable, resolved
      server-side) — a narrower and stronger proof than "member of this
      tenant", and every read there is a targeted lookup by an ID the
      caller already legitimately holds, never a list/enumerate.
    - background jobs (orphan_sweep, capability_reconcile,
      session_reconcile): their job is, by design, to scan every tenant's
      stalled/orphaned state. Nothing here ever returns tenant-scoped data
      to an end user — it only ever transitions status columns or cleans
      infrastructure, the same actions P9/P12/P16 already proved safe
      irrespective of tenant.
    """
    token = current_tenant.set(ALL_TENANTS)
    try:
        yield
    finally:
        current_tenant.reset(token)


@asynccontextmanager
async def all_tenants_session(session_factory):
    """Convenience: open a session already inside use_all_tenants(), for
    the module-level `async with async_session_factory() as db:` call
    sites this phase converts in mcp_gateway.py and the background
    reconciliation modules."""
    with use_all_tenants():
        async with session_factory() as db:
            yield db


def _criteria_fn(tenant: Union[uuid.UUID, _AllTenants, None]):
    """Returns the callable `with_loader_criteria` wants (entity -> SQL
    expression), evaluated fresh per mapped class/alias at statement-
    compile time -- not a pre-built expression -- so `include_aliases=True`
    correctly rewrites it if this table is ever joined/aliased."""
    if tenant is None:
        return lambda cls: sql_false()  # fail closed
    return lambda cls: cls.tenant_id == tenant


def _install_tenant_scoping() -> None:
    from sqlalchemy import event

    @event.listens_for(Session, "do_orm_execute")
    def _scope_tenant_queries(execute_state) -> None:
        if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
            return
        tenant = current_tenant.get()
        if tenant is ALL_TENANTS:
            return  # explicit, reviewed cross-tenant opt-out -- no criteria added
        criteria_fn = _criteria_fn(tenant)
        # with_loader_criteria takes one entity at a time (verified against
        # its real signature, not assumed) -- one .options() call per
        # tenant-scoped model, all sharing the same criteria function.
        for model in TENANT_SCOPED_MODELS:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(model, criteria_fn, include_aliases=True)
            )


_install_tenant_scoping()
