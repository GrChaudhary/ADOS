"""ados_app: a non-superuser runtime role

Revision ID: f4a5b6c7d8e9
Revises: d1e2f3a4b5c6
Create Date: 2026-08-12 00:00:00.000000

P10 — the shipped compose stack connects the backend with the same role
(`ados`, from POSTGRES_USER) that runs migrations. That role is a Postgres
superuser, which — as the previous migration's own comment already flagged
("becomes real the moment a non-superuser application role exists") — makes
every REVOKE in this schema a no-op: superusers bypass ACL checks, REVOKE
included. This migration is that non-superuser role.

`ados_app` gets ordinary DML (SELECT/INSERT/UPDATE/DELETE) on every table via
GRANT + ALTER DEFAULT PRIVILEGES (so tables future migrations add are covered
automatically, without a human remembering to re-grant), because the backend
process genuinely needs that across its whole schema, not only the Prime
Agent tables — restricting it further would break real, unrelated features
(moa_task_breakers, llm_provider_settings, ...) that legitimately DELETE.

It does NOT get CREATE on the schema, and it does not own any table (`ados`,
the migration role, does) — so DDL (CREATE/ALTER/DROP/TRUNCATE) on anything
is refused by ownership rules alone, no REVOKE needed for that part.

On top of the blanket grant, DELETE is explicitly revoked on the three
tables that are the Prime Agent integration's actual audit spine
(`missions`, `runtime_sessions`, `capability_requests`) — no reviewed code
path deletes a row from any of them (grep-verified), so losing DELETE costs
nothing real and closes the one way a compromised or buggy runtime process
could make the audit trail incomplete rather than merely wrong. The same is
done for `capability_promotion_events`, completing revision `7f551a8ccce0`'s
own stated intent now that there is finally a non-superuser role for it to
bind to.

Role creation is idempotent (checked against pg_roles) because this same
migration runs against two independent databases on one shared Postgres
cluster (`ados`, `ados_test` — see conftest.py) and roles are cluster-wide,
not per-database; the second run must not fail trying to recreate one that
already exists. Downgrade reverses the grants but deliberately does not
DROP ROLE — the role may still be depended on (granted, owning nothing, but
referenced) by the OTHER database's still-upgraded state, and dropping a
cluster-wide object from a single database's migration chain is not a safe
symmetric inverse. See this file's own downgrade() for the exact scope.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Dev-simplicity credential, matching the existing ados:ados convention in
# docker-compose.yml — this is a local-evaluation stack, not a hardened
# production credential store (see docker-compose.yml's own top-of-file
# note). A real deployment supplies its own password out of band.
_APP_ROLE = "ados_app"
_APP_PASSWORD = "ados_app"

_APPEND_ONLY_TABLES = ("missions", "runtime_sessions", "capability_requests")


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{_APP_ROLE}') THEN
                CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_PASSWORD}';
            END IF;
        END
        $$;
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO {_APP_ROLE}', current_database());
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {_APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE ados IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE ados IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {_APP_ROLE}"
    )

    for table in _APPEND_ONLY_TABLES:
        op.execute(f"REVOKE DELETE ON {table} FROM {_APP_ROLE}")
    # Completes revision 7f551a8ccce0's own deferred intent: that REVOKE
    # targeted CURRENT_USER (the superuser `ados`), a documented no-op. This
    # is the same guarantee, finally binding on a role it can actually bind.
    op.execute(f"REVOKE UPDATE, DELETE ON capability_promotion_events FROM {_APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {_APP_ROLE}")
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE ados IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {_APP_ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE ados IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {_APP_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_APP_ROLE}")
    # Deliberately not DROP ROLE — see this module's own docstring.
