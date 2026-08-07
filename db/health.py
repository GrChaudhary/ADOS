"""
Connectivity probe — shaped like the old Cloudant client's
get_health_status() (same field names), so backend/app/routers/
integrations.py's "postgresql" health card needed no shape changes when
it replaced the "cloudant_nosql" one.
"""

import time
from typing import Any, Dict

from sqlalchemy import text

from .engine import engine


async def get_health_status() -> Dict[str, Any]:
    base = {
        "id": "postgresql",
        "name": "PostgreSQL",
        "auth": "Password (local dev) — see DATABASE_URL",
        "module": "db/engine.py",
        "description": "Primary datastore for incidents, users, capability manifests, and everything else "
        "that used to live only in memory or best-effort in Cloudant.",
        "capabilities": ["QueryDatabase", "PersistIncident", "PersistUser", "PersistCapabilityManifest"],
    }
    start = time.time()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.time() - start) * 1000, 1)
        return {**base, "status": "Connected 🟢", "connected": True, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = round((time.time() - start) * 1000, 1)
        return {**base, "status": f"Error: {exc}", "connected": False, "latency_ms": latency_ms}


async def check_connectivity_or_raise() -> None:
    """Called once at app startup (main.py's lifespan) — fail fast and
    loud if Postgres is unreachable, matching the existing "honest status"
    convention used for Cloudant/NLU/TTS today (never silently degrade)."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
