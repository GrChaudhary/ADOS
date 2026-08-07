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

    # Observability (backend/app/observability.py). JSON is right for a log
    # shipper; set log_json=false locally when you'd rather read it yourself.
    log_level: str = "INFO"
    log_json: bool = True

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

    # IBM Watson Natural Language Understanding
    nlu_api_key: str = ""
    nlu_url: str = ""

    # IBM Watson Text to Speech
    tts_api_key: str = ""
    tts_url: str = ""

    # Phase 5B: the Next.js dev server (frontend-next/) runs on a different
    # origin than this API, unlike frontend/'s same-origin static mount —
    # needs CORS. EventSource requests bypass the Next.js rewrite proxy and
    # hit this origin directly, so this must stay enabled even with the proxy.
    frontend_dev_origin: str = "http://localhost:3000"


settings = Settings()
