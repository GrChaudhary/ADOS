# ADOS

A multi-agent orchestration platform. One Main Orchestrating Agent (MOA)
dynamically plans work across domain pods — HR, IT, Finance, Manufacturing —
and every individual action it proposes is governed, tiered by risk, and
routed to a human when it needs one. New capabilities can be onboarded from
an MCP server, an OpenAPI spec, or raw code, each verified in a Docker
sandbox before it is ever callable.

Design record: [`docs/`](docs/) (RFC-style chapters) and [`adr/`](adr/)
(frozen decisions). Start with [`docs/000-vision.md`](docs/000-vision.md) and
[`docs/001-system-architecture.md`](docs/001-system-architecture.md).

## Run it

```bash
docker compose up --build
open http://localhost:3000
```

That brings up Postgres, Kafka, the schema migration, the FastAPI backend
(`localhost:8000`), and the Next.js frontend (`localhost:3000`).

On first boot the backend generates passwords for the seeded RBAC accounts
and prints them once:

```bash
docker compose logs backend | grep -A6 "Seeded RBAC accounts"
```

They are never reset on later boots, so capture them then. To reset one
later: `scripts/reset_user_password.py`.

### Configuration

Copy [`.env.example`](.env.example) to `.env` and fill in what you need. The
values worth knowing about:

| Variable | Default | Notes |
|---|---|---|
| `JWT_SECRET` | dev-only fallback | **Set this.** Anyone who can read this repo can forge tokens signed with the default. Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. |
| `DATABASE_URL` | local Postgres | Compose sets this itself. |
| `EVENT_BUS_BACKEND` | `memory` | Or `redis`, or `kafka` (the broker is already in the compose stack). |
| `NEMOTRON_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | unset | Without at least one, the MOA and both LangGraph agents report "not configured" and refuse to run rather than guess. |
| `SEED_DEMO_DATA` | `false` | Loads 220 fabricated manufacturing incidents into the dashboard and KPIs. For demos and screenshots, not deployments. |

### Developing without containers

```bash
docker compose up -d postgres kafka
./.venv/bin/alembic upgrade head
./scripts/run-backend.sh                    # backend on :8000
cd frontend-next && npm install && npm run dev   # frontend on :3000
```

### Tests

```bash
docker compose up -d postgres kafka   # the suite is live-only against both
pytest -q                             # 455 tests
```

There is no mock substitute for Postgres or Kafka by deliberate convention —
with them stopped the suite reports setup errors rather than skips. The
capability-onboarding sandbox tests do skip cleanly when Docker is
unavailable. CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs
all of it plus the frontend typecheck, lint, build, and both image builds.

## Status

This runs, and the test suite is real. It is **not production-hardened** —
the known gaps are tracked honestly in
[`ADOS_OBSIDIAN/TODO - Productization.md`](ADOS_OBSIDIAN/TODO%20-%20Productization.md).
The ones to know before deploying it anywhere real:

- **Single process only.** Paused MOA/ITSM approvals live in per-process
  state, so a second worker or replica would drop roughly half of all
  approve/reject calls, and a restart loses in-flight approvals. (Incidents
  are durable; MOA is not, yet.)
- **No observability.** No metrics, structured logs, or tracing.
- **Simulated actions.** `ConsoleConnector` fulfills every capability and
  logs instead of acting. The ServiceNow and SAP connectors are real code but
  have never been run against a live instance.
- **The compose stack is not a deployment.** Superuser Postgres role, no TLS,
  and the backend mounts the host Docker socket for the onboarding sandbox.
