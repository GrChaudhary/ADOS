"""
Application settings, read from environment / .env — see ../../.env.example
and docs/009-security.md (secrets are brokered via env, never hardcoded).
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]  # ADOS/

# Settings() below reads .env for its OWN fields, but pydantic-settings does
# that in-memory — it never populates os.environ. Several modules deliberately
# read os.environ live on every call instead of going through Settings
# (knowledge/local_llm_client.py, nlu_client.py, tts_client.py — they re-check
# per call so a key added at runtime takes effect without a restart), and to
# those an .env-only key was simply invisible: a valid NEMOTRON_API_KEY sat in
# .env while MOA reported "not_configured" and refused to run. Load it here,
# once, before anything imports those clients.
#
# override=False on purpose: a real exported environment variable outranks the
# file, which is what makes tests/deployments that set vars explicitly (see
# conftest.py's DATABASE_URL) keep winning.
load_dotenv(_REPO_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = "local"

    # executive/seed_data.py's 220 fabricated manufacturing incidents (20
    # hand-written "hero" records + 200 generated) used to load
    # unconditionally at every startup, so a fresh deployment's dashboards,
    # KPIs, and Decision Memory opened full of incidents that never happened.
    # Useful for a demo, wrong for a product — now opt-in. Consumed by
    # backend/app/main.py's lifespan and backend/app/routers/memory.py.
    seed_demo_data: bool = False

    # How often each process re-reads llm_provider_settings from Postgres.
    #
    # knowledge/local_llm_client.py caches provider keys/models in process
    # memory, pushed by backend/app/routers/settings.py after every save. That
    # push only reaches the process that served the request — save a key on
    # replica A and replica B keeps reporting "not configured" until it
    # restarts. It can't pull on demand either: get_api_key()/is_configured()
    # are called synchronously from deep inside agent code already running on
    # the event loop, so they can't await a query.
    #
    # A periodic refresh closes the gap without touching that hot path. The
    # cost of staleness is bounded and low (a key saved seconds ago isn't yet
    # visible on other replicas); the cost of a miss is a task refusing to run.
    # Set to 0 to disable (single-process deployments don't need it — the
    # push already covers them).
    llm_settings_refresh_seconds: int = 30

    # How often each process reconciles abandoned runtime sessions and sweeps
    # their orphaned resources (orchestrate/runtime/session_reconcile.py,
    # orchestrate/runtime/orphan_sweep.py).
    #
    # P6-D made a session's terminal state failure-safe against an exception
    # inside the process serving it; it cannot help against the process
    # itself dying (SIGKILL, an OOM kill, a restart mid-mission) — three real
    # sessions from Aug 9 were exactly that, stuck at `running` forever until
    # reconciled by hand once. Both passes are safe to run unattended: each
    # only ever acts on a resource it can independently prove is either
    # already provably dead (an expired token) or already ADOS-owned (a
    # matching `ados.session_id` label / an exact recorded workspace path) —
    # see those modules' own docstrings for the safety argument in full.
    #
    # Set to 0 to disable (an operator who prefers scripts/sweep_orphans.py
    # run by hand, or from their own cron, loses nothing by turning this off).
    orphan_reconcile_interval_seconds: int = 300

    # Observability (backend/app/observability.py). JSON is right for a log
    # shipper; set log_json=false locally when you'd rather read it yourself.
    log_level: str = "INFO"
    log_json: bool = True

    # P11 admission control (integrations/admission_control.py,
    # backend/app/mcp_gateway.py) — bounds on one ADOS process, sized for
    # controlled internal use (Model A), not a distributed limiter. See
    # docs/prime-agent-integration/19-metrics-and-alerting.md's scope
    # boundary paragraph. Every one of these is an operator-tunable ceiling,
    # not a claim about real capacity anyone has load-tested.
    max_concurrent_prime_missions: int = 3
    max_concurrent_capability_executions: int = 10
    max_pending_approvals: int = 50
    max_capability_requests_per_session: int = 200

    # P12 — the two concurrency gates above are now globally enforced across
    # processes via admission_leases (integrations/admission_control.py), and
    # this is a genuinely different mechanism: a rate limit on how often
    # RunPrimeRLMAgent can be *started*, independent of concurrency. See
    # integrations/rate_limiter.py's module docstring for the full
    # purpose/default/enforcement/metric/alert writeup this phase's own
    # instructions require. max<=0 disables it.
    mission_start_rate_limit_max: int = 20
    mission_start_rate_limit_window_seconds: int = 300

    # P12 — the centralized periodic loop's reclaim pass (orchestrate/runtime/
    # admission_lease_reclaim.py). Lease max age must stay comfortably above
    # the longest real hub.invoke() call this deployment allows (a Prime
    # Agent mission's own max_wall_clock_seconds is the long pole) or a
    # still-genuinely-running call's lease could be reclaimed out from under
    # it — 1800s matches the same generous-headroom reasoning
    # session_reconcile.py's token grace period already uses. Event
    # retention is pure storage hygiene, not correctness (the rate check
    # always filters by its own window regardless of how much history sits
    # in the table).
    admission_lease_max_age_seconds: float = 1800.0
    rate_limit_event_retention_seconds: float = 3600.0

    # Dead-host reclamation (orchestrate/runtime/node_heartbeat.py) — the one
    # genuine Model-C engineering blocker named by the Model-C Decision Gate
    # (docs/prime-agent-integration/31-model-c-decision-gate.md, Phase 2).
    # Conservative on purpose: comfortably above several missed
    # orphan_reconcile_interval_seconds ticks so a host that is merely slow
    # or transiently partitioned from Postgres is never declared dead — see
    # node_heartbeat.py's own docstring for the full safety argument.
    node_heartbeat_dead_after_seconds: float = 900.0

    # Real persistence (db/) — dev-only default matching docker-compose.yml's
    # postgres service defaults, same convention as jwt_secret's dev-only
    # fallback below: safe for a fresh clone to import without `.env` set,
    # not safe to rely on in a real deployment.
    database_url: str = "postgresql+asyncpg://ados:ados@localhost:5432/ados"

    # Event bus — "memory" (default, zero external deps), "redis", or
    # "kafka". docs/010-api-contracts.md's bus-technology question is
    # resolved (infrastructure/EVENT_BUS_COMPARISON.md); default stays
    # "memory" so a fresh clone/test run needs no external broker unless
    # EVENT_BUS_BACKEND is explicitly set.
    event_bus_backend: str = "memory"
    event_bus_url: str = "redis://localhost:6379/0"
    event_bus_stream: str = "ados:events"
    kafka_bootstrap_servers: str = "localhost:29092"
    kafka_topic: str = "ados.events"

    # Service-to-service auth: shared-secret bearer token. Superseded by
    # real per-user RBAC (backend/app/rbac.py) for all HTTP endpoints;
    # kept only as a fallback constant nothing currently reads, in case a
    # future non-interactive service caller needs one. See jwt_secret below
    # for the real auth mechanism.
    service_auth_token: str = "dev-local-only-token"

    # RBAC (backend/app/rbac.py) — signs/verifies session JWTs. Generate a
    # real value for .env with `python -c "import secrets; print(secrets.token_hex(32))"`;
    # the fallback below is dev-only and must not be relied on in a real
    # deployment (anyone who reads this source could forge tokens).
    jwt_secret: str = "dev-only-insecure-jwt-secret-change-me"

    # Password given to the 5 seeded RBAC accounts on FIRST boot only
    # (user_store.bootstrap_users). Empty means "generate a random one per
    # account and print it once" — safe, but unrecoverable the moment that
    # console output scrolls away or the Postgres volume is recreated, which
    # is how people end up permanently locked out of their own instance.
    #
    # Set it in .env to make seeding reproducible: wipe the database, boot
    # again, and the same known password works. It is NOT a backdoor into an
    # existing instance — bootstrap_users still refuses to touch accounts
    # that already exist, so changing this later does nothing until the user
    # store is empty again. To change a live password use
    # scripts/reset_user_password.py.
    seed_password: str = ""

    # IBM Watson Natural Language Understanding
    nlu_api_key: str = ""
    nlu_url: str = ""

    # IBM Watson Text to Speech
    tts_api_key: str = ""
    tts_url: str = ""

    # P16 — identifies which physical/virtual host this ADOS process is
    # running on. Only consumer today: orchestrate/runtime/orphan_sweep.py
    # stamps it onto RuntimeSessionRow.owner_host at session creation and
    # filters claim_batch by it, so a sweeper never concludes a resource
    # that actually lives on a DIFFERENT host's Docker daemon is "absent"
    # just because it is invisible from here. Empty string means "resolve
    # socket.gethostname() at the call site" — a single-host deployment
    # (Model A/B, today's only deployed shape) never needs to set this.
    node_id: str = ""

    # Phase 5B: the Next.js dev server (frontend-next/) runs on a different
    # origin than this API, unlike frontend/'s same-origin static mount —
    # needs CORS. EventSource requests bypass the Next.js rewrite proxy and
    # hit this origin directly, so this must stay enabled even with the proxy.
    frontend_dev_origin: str = "http://localhost:3000"


settings = Settings()
