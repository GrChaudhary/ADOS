#!/usr/bin/env bash
# Runs the Phase 1 FastAPI backend locally.
set -euo pipefail
cd "$(dirname "$0")/.."
./.venv/bin/uvicorn backend.app.main:app --reload --port 8000
