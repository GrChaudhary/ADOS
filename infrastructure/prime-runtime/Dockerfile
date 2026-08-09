# ADOS Prime Agent Runtime — the execution plane, containerized.
#
# Built from the Prime Agent SOURCE tree (not npm): the published
# @earendil-works/pi-coding-agent package versions diverge from prime-agent's
# own (0.7.1 is not on the registry; latest there is 0.84.1), so pinning to the
# source we actually reviewed is the only way to get a reproducible runtime
# that matches docs/prime-agent-integration/.
#
# Build context is the prime-agent repository root:
#   docker build -f ADOS/infrastructure/prime-runtime/Dockerfile -t ados-prime-runtime:0.7.1 ../prime-agent
#
# SECURITY POSTURE — read before changing anything here.
# Prime Agent executes model-generated Python with the permissions of whoever
# runs it; its own README states the worker/kernel processes are "not a
# security sandbox". This image is the boundary that makes that acceptable:
#   * runs as a non-root user
#   * no ADOS credentials, no database URL, no downstream system credentials
#   * the only secrets injected at run time are the LLM provider key and the
#     per-session ADOS_MCP_TOKEN, which is identity-only and resolves to a
#     server-side capability grant
#   * the workspace is a disposable bind mount, never the ADOS repo or $HOME
# Resource limits and network placement are applied by the caller
# (orchestrate/runtime/prime_container.py), not baked in here.

FROM node:22-bookworm-slim AS build

WORKDIR /opt/prime-agent

# git: the launcher shells out to `git describe` for a build id.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
COPY packages ./packages
COPY tsconfig.base.json tsconfig.json biome.json ./
# The Python kernel shim (`rlm`), installed into the kernel venv in the runtime
# stage. It has to be copied here too, because that stage copies /opt/prime-agent
# wholesale from this one.
COPY prime-agent-runtime ./prime-agent-runtime

# `npm ci` needs the workspace package.json files present, which the COPY above
# provides. The build order is fixed by the root package.json's build script
# (tui -> ai -> agent -> coding-agent) because they depend on each other's dist.
RUN npm ci --no-audit --no-fund \
    && npm run build

# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS runtime

# python3 + venv: the agent's single tool is a persistent IPython kernel, so
# the Python runtime is not optional — without it the agent has no way to act.
# ripgrep/fd are the search tools the agent shells out to (~/.prime/agent/bin
# holds them in a host install).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip git ca-certificates ripgrep fd-find curl \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

# uv is what Prime Agent uses to provision the kernel. PRIME_AGENT_KERNEL_PYTHON
# below means it should never need to, but installing it costs little and turns
# a hard failure into a fallback if the pinned kernel is ever unusable.
RUN curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

# uid 10001 to match the convention in ADOS's own images.
RUN groupadd -g 10001 prime && useradd -u 10001 -g prime -m -s /bin/bash prime

COPY --from=build --chown=prime:prime /opt/prime-agent /opt/prime-agent

# The kernel venv. PRIME_AGENT_KERNEL_VENV is the documented override
# (packages/coding-agent/src/core/kernel/bootstrap.ts) — without it the agent
# looks for ~/.prime/agent/kernel-venv and tries to build one at first run,
# which would mean a network install inside a locked-down container.
# Under /home/prime, NOT /opt. Prime Agent acquires a bootstrap lock by
# creating a SIBLING directory next to the venv ("<venv>.bootstrap.lock"), so
# the venv's parent has to be writable by the runtime user. With the venv in
# root-owned /opt the agent died with
#   EACCES: permission denied, mkdir '/opt/kernel-venv.bootstrap.lock'
# and, because the IPython kernel is its ONLY tool, that one permission error
# left it unable to read a file, run a command, or call any ADOS capability.
# PRIME_AGENT_KERNEL_PYTHON, not just _VENV. Pointing at the VENV still lets
# the agent try to auto-bootstrap it, which requires `uv` and network access at
# first run — inside a locked-down container that fails with
#   "uv is required to set up the Python kernel"
# Pointing at a PYTHON that already has ipykernel + prime-agent-runtime is the
# documented way to skip auto-bootstrap entirely (the error message says so),
# which is what we want: the kernel is provisioned at build time, deterministically.
ENV PRIME_AGENT_KERNEL_VENV=/home/prime/kernel-venv \
    PRIME_AGENT_KERNEL_PYTHON=/home/prime/kernel-venv/bin/python
# The override is validated, not trusted. ensureKernelPythonUncached()
# (packages/coding-agent/src/core/kernel/bootstrap.ts) checks THREE things and
# throws if any is missing:
#   1. ipykernel imports
#   2. prime-agent-runtime satisfies RUNTIME_READY_CHECK
#   3. EVERY package in DEFAULT_RLM_EXTRA_PACKAGES imports
# An image satisfying only 1 and 2 looks completely healthy — the venv exists,
# `import rlm` works, the container starts, the model runs — and then every
# single tool execution fails with
#   "PRIME_AGENT_KERNEL_PYTHON points to a Python missing default Python
#    packages (requests, yaml (PyYAML), tomli, ...)"
# because the check is lazy, on first tool use. An 18-tool-call run produced 18
# identical failures and then a confidently fabricated report. Keep this list in
# sync with DEFAULT_RLM_EXTRA_PACKAGES; tests/test_prime_runtime_image.py parses
# that source and fails if the two ever drift.
# These are also what the system prompt advertises to the model as
# "Pre-installed Python packages" (core/prompts/rlm.ts), so a partial install
# makes the model's own instructions wrong.
# dill is the kernel's state-snapshot dependency (STATE_SNAPSHOT_REQUIREMENT).
# The override path does not check for it, but the normal bootstrap installs it
# and session resume uses it, so a pinned kernel without it is subtly degraded.
RUN python3 -m venv /home/prime/kernel-venv \
    && /home/prime/kernel-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /home/prime/kernel-venv/bin/pip install --no-cache-dir \
         /opt/prime-agent/prime-agent-runtime \
         ipykernel dill mcp \
         requests httpx pyyaml tomli python-dotenv \
         pandas numpy scipy beautifulsoup4 lxml pydantic tyro

# The ADOS capability skill: a Python-backed skill (McpIntegration subclass)
# that the kernel imports to reach the ADOS MCP gateway. This is the ONLY
# route from the runtime back into ADOS.
COPY --chown=prime:prime ados_skill /opt/ados-skill
RUN /home/prime/kernel-venv/bin/pip install --no-cache-dir /opt/ados-skill

# chown AFTER every pip install, not before. Prime Agent does not merely READ
# the kernel venv — it manages it, and on startup it rewrites entries it wants
# to own. Files left root-owned by a later `pip install` made it fail with
#   EACCES: permission denied, unlink '.../site-packages/ados/__init__.py'
# which, since the kernel is its only tool, disabled the agent completely while
# every other part of the image looked correct.
RUN chown -R prime:prime /home/prime

USER prime
ENV HOME=/home/prime \
    PRIME_AGENT_CLI=/opt/prime-agent/packages/coding-agent/dist/bundle/cli.js \
    NODE_ENV=production

# Skills are discovered from ~/.prime/agent/skills; SKILL.md is what makes the
# capability visible to the model rather than merely importable.
RUN mkdir -p /home/prime/.prime/agent/skills \
    && cp -r /opt/ados-skill/skill_manifest /home/prime/.prime/agent/skills/ados

WORKDIR /work

# The container idles; ADOS execs the RPC process into it so the session can
# outlive a single prompt and teardown stays an explicit, auditable step.
CMD ["sleep", "infinity"]
