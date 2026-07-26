"""
Application settings, read from environment / .env — see ../../.env.example
and docs/009-security.md (secrets are brokered via env, never hardcoded).
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[2]  # ADOS/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = "local"

    # Event bus — "memory" (default, zero external deps) or "redis".
    # See docs/010-api-contracts.md open question on bus technology; MVP
    # ships pluggable so the choice isn't load-bearing yet.
    event_bus_backend: str = "memory"
    event_bus_url: str = "redis://localhost:6379/0"
    event_bus_stream: str = "ados:events"

    # Service-to-service auth: shared-secret bearer token for the MVP.
    # docs/009-security.md flags real IdP/OAuth2 integration as a later
    # step; this is intentionally minimal for Phase 1.
    service_auth_token: str = "dev-local-only-token"

    # IBM watsonx Orchestrate (unused by backend directly yet; present so
    # Settings has one place that mirrors .env.example end to end)
    wo_instance: str = ""
    wo_api_key: str = ""

    # Phase 5B: the Next.js dev server (frontend-next/) runs on a different
    # origin than this API, unlike frontend/'s same-origin static mount —
    # needs CORS. EventSource requests bypass the Next.js rewrite proxy and
    # hit this origin directly, so this must stay enabled even with the proxy.
    frontend_dev_origin: str = "http://localhost:3000"


settings = Settings()
