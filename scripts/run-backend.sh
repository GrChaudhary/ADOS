#!/usr/bin/env bash
# Runs the Phase 1 FastAPI backend locally.
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env into the process environment. Every integration client
# (knowledge/cloudant_client.py, nlu_client.py, tts_client.py,
# local_llm_client.py, integrations/connectors/watsonx_itsm.py)
# deliberately gates is_configured()/execute() on literal os.environ
# membership (not just pydantic Settings) so tests can simulate an
# unconfigured state by deleting env vars - see their is_configured()
# comments. Without this, .env values are invisible to those checks.
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
