# ADOS backend — FastAPI + the orchestrator, agents, and onboarding pipeline.
#
# Until this file existed there was no packaged form of ADOS at all: the only
# way to run it was scripts/run-backend.sh against a hand-built .venv on one
# developer's laptop (see docs/PRODUCTIZATION.md, Stage 1).
#
# Build:  docker build -t ados-backend .
# Run:    docker compose up  (see docker-compose.yml — that wires Postgres,
#         Kafka, migrations, and the frontend together)

# The docker CLI only — no daemon. Debian's docker.io package pulls in the
# whole engine and still doesn't put a `docker` binary on PATH (verified:
# it ships docker-init and nothing else usable here), so take the official
# static client instead. It talks to the host daemon over the socket
# docker-compose.yml mounts.
FROM docker:27-cli AS docker-cli

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# - git: orchestrate/onboarding/inspector.py clones capability source repos.
# - curl: HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
    && rm -rf /var/lib/apt/lists/*

# orchestrate/onboarding/sandbox_runner.py shells out to `docker` to build and
# run sandboxed capability images. It gates on shutil.which("docker"), so the
# backend still starts if this is removed — the onboarding pipeline just
# reports Docker as unavailable instead of crashing. See the security note on
# the socket mount in docker-compose.yml before carrying this to a real
# deployment.
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

# Dependencies first so source edits don't invalidate the install layer.
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Non-root by default. The container joins the host's docker group at runtime
# (docker-compose.yml's group_add) rather than running as root just to reach
# the socket.
RUN useradd --create-home --uid 10001 ados \
    && chown -R ados:ados /app
USER ados

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# --workers is deliberately absent, and this is load-bearing, not an
# oversight: paused MOA/ITSM approvals live in per-process state
# (app.state.moa_pending_tasks + LangGraph's InMemorySaver), so a second
# worker or replica would 404 roughly half of all approve/reject calls.
# Scaling out requires the Postgres-backed checkpointer in Stage 2 of
# docs/PRODUCTIZATION.md. Until then: one process.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
