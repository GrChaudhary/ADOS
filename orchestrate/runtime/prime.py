"""
PrimeAgentRuntime — ADOS drives a real Prime Agent process inside a container.

This is the DOWNWARD half of the runtime boundary. The upward half (Prime Agent
asking ADOS for capabilities) is backend/app/mcp_gateway.py and does not pass
through here at all: the runtime reaches ADOS over HTTP MCP, so this adapter
never relays capability requests and cannot forge one.

Two rules this file exists to enforce.

**The container is the boundary.** Prime Agent executes model-generated Python
with the permissions of whoever runs it, and its own README states the worker
and kernel processes are "not a security sandbox". Nothing here ever runs it on
the host. The container gets a disposable workspace, resource limits, a
dedicated network, and exactly two secrets: the LLM provider key and an
identity-only ADOS session token.

**Observed effects are authoritative.** Exit code 0 is not success. A model was
observed emitting `agent_end` with empty content, zero tool executions and exit
0 — a clean report of having done nothing at all. Completion is asserted from
kernel tool executions and a final answer, and the authoritative record of what
was *executed* comes from the gateway's own rows, never from the agent.
"""

import asyncio
import json
import logging
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import AgentSessionSpec, RuntimeEvent, SessionOutcome, SessionState
from .prime_image import IMAGE_TAG

logger = logging.getLogger("ados.runtime.prime")

# Dedicated network: the runtime sits on its own bridge, not on ADOS's compose
# network, so it cannot reach Postgres, Kafka, or any other internal service.
# It is NOT an egress allowlist — the container can still reach the public
# internet, which it must, to call the LLM. Narrowing that needs a filtering
# proxy and is deliberately not claimed here.
NETWORK_NAME = "ados-runtime-net"

_CONTAINER_PREFIX = "ados-prime-"

_ADOS_SKILL_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "infrastructure" / "prime-runtime" / "ados_skill" / "skill_manifest" / "SKILL.md"
)

# Prime Agent's event vocabulary -> ADOS's. Anything unmapped is dropped rather
# than passed through, so ADOS's event stream never depends on upstream shapes.
_EVENT_MAP = {
    "session": "runtime.session.started",
    "tool_execution_start": "runtime.tool.started",
    "tool_execution_end": "runtime.tool.finished",
    "turn_end": "runtime.turn.completed",
    "agent_end": "runtime.session.completed",
    # Carries the model's own token accounting (input/output/cacheRead/
    # cacheWrite/totalTokens). Without it a slow run is unattributable: "the
    # turn took 697 seconds" says nothing about whether the prompt grew, the
    # provider queued, or the kernel blocked. Two acceptance runs were spent
    # guessing at that before this was mapped.
    "message_end": "runtime.model.message",
    # Provider failures. Without these a rate-limited or rejected model
    # call is invisible and the run just reports "it did nothing" — which
    # is true but useless. Two acceptance runs were spent rediscovering a
    # 429 and a 413 that were sitting in this stream all along.
    "auto_retry_start": "runtime.provider.retry",
    "auto_retry_end": "runtime.provider.retry_end",
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _run(*args: str, timeout: float = 60.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"timed out: {' '.join(args)}")
    return proc.returncode, out.decode(errors="replace")


async def ensure_network() -> None:
    code, _ = await _run("docker", "network", "inspect", NETWORK_NAME, timeout=20.0)
    if code != 0:
        await _run("docker", "network", "create", NETWORK_NAME, timeout=30.0)


class PrimeAgentRuntime:
    """One containerized Prime Agent session."""

    def __init__(
        self,
        *,
        mcp_url: str,
        provider: str = "groq",
        model: str = "llama-3.3-70b-versatile",
        provider_key_env: str = "GROQ_API_KEY",
        provider_key: Optional[str] = None,
        # Custom OpenAI-compatible providers, written to the session's
        # models.json. Needed for anything not built in (e.g. NVIDIA NIM).
        models_json: Optional[Dict[str, Any]] = None,
        image: str = IMAGE_TAG,
        memory: str = "2g",
        cpus: str = "2",
        pids_limit: str = "512",
    ):
        self.mcp_url = mcp_url
        self.provider = provider
        self.model = model
        self.provider_key_env = provider_key_env
        self.provider_key = provider_key
        self.models_json = models_json
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit

        self.container_name: Optional[str] = None
        self.workspace: Optional[Path] = None
        self.state: SessionState = SessionState.CREATED

    # -- workspace ---------------------------------------------------------

    def _prepare_workspace(self, spec: AgentSessionSpec, token: str) -> Path:
        """A disposable directory, seeded with the mission's artifacts and
        nothing else. Never the ADOS repo, never $HOME."""
        ws = Path(tempfile.mkdtemp(prefix=f"ados-mission-{spec.mission_id[:8]}-"))
        for name, content in spec.workspace_files.items():
            target = ws / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)

        # Per-session agent config dir, pointed at by
        # PRIME_AGENT_CODING_AGENT_DIR. Redirecting the whole dir (rather than
        # writing into $HOME in the image) keeps every session's provider
        # config, MCP wiring and skills isolated and disposable — and means the
        # image itself carries no ADOS endpoint or provider choice.
        agent_dir = ws / ".agent"
        (agent_dir / "skills" / "ados").mkdir(parents=True, exist_ok=True)

        # Declaring the gateway under mcpServers is what lets the kernel skill
        # resolve it. The token is referenced by env var name only, so the
        # workspace on disk never holds a credential.
        (agent_dir / "settings.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "ados": {
                            "type": "http",
                            "url": self.mcp_url,
                            "bearerTokenEnvVar": "ADOS_MCP_TOKEN",
                        }
                    }
                },
                indent=2,
            )
        )

        # Custom OpenAI-compatible providers (NVIDIA NIM and friends) live in
        # models.json. `apiKey` names an ENV VAR, not a literal.
        if self.models_json:
            (agent_dir / "models.json").write_text(json.dumps(self.models_json, indent=2))

        # Redirecting the agent dir also redirects skill discovery, so the
        # image's copy at /home/prime/.prime/agent/skills is no longer on the
        # path — the manifest has to be placed here or the model never learns
        # the ADOS capability route exists.
        if _ADOS_SKILL_MANIFEST.is_file():
            shutil.copy2(_ADOS_SKILL_MANIFEST, agent_dir / "skills" / "ados" / "SKILL.md")

        (ws / ".sessions").mkdir(exist_ok=True)
        return ws

    # -- container ---------------------------------------------------------

    async def start(self, spec: AgentSessionSpec, token: str) -> None:
        self.state = SessionState.STARTING
        await ensure_network()

        self.container_name = f"{_CONTAINER_PREFIX}{spec.session_id[:12]}"
        self.workspace = self._prepare_workspace(spec, token)

        env = {
            # Identity-only. Resolves server-side to this mission's grant.
            "ADOS_MCP_TOKEN": token,
            "ADOS_MCP_URL": self.mcp_url,
            self.provider_key_env: self.provider_key or "",
            # Redirects models.json / settings.json / skills discovery into
            # the per-session workspace (see _prepare_workspace).
            "PRIME_AGENT_CODING_AGENT_DIR": "/work/.agent",
            # Telemetry off: this is an automated runtime, not a user session.
            "PRIME_AGENT_TELEMETRY": "0",
        }
        env_args: List[str] = []
        for k, v in env.items():
            env_args += ["-e", f"{k}={v}"]

        args = [
            "docker", "run", "-d",
            "--name", self.container_name,
            "--network", NETWORK_NAME,
            # host-gateway so the container can reach the ADOS gateway running
            # on the host without host networking.
            "--add-host", "host.docker.internal:host-gateway",
            "--memory", self.memory,
            "--cpus", self.cpus,
            "--pids-limit", self.pids_limit,
            "-v", f"{self.workspace}:/work",
            "-w", "/work",
            *env_args,
            self.image,
            "sleep", "infinity",
        ]
        code, out = await _run(*args, timeout=120.0)
        if code != 0:
            self.state = SessionState.FAILED
            raise RuntimeError(f"container failed to start: {out[-2000:]}")

        self.state = SessionState.RUNNING
        logger.info(
            "Prime Agent runtime container started",
            extra={"container": self.container_name, "mission_id": spec.mission_id},
        )

    async def run_objective(self, spec: AgentSessionSpec) -> SessionOutcome:
        """Sends the objective over RPC and consumes the event stream."""
        assert self.container_name, "start() first"

        events: List[RuntimeEvent] = []
        tool_calls = 0
        tool_ok = 0
        tool_err = 0
        final_answer: Optional[str] = None
        runtime_session_id: Optional[str] = None
        failure: Optional[str] = None
        provider_error: Optional[str] = None

        cmd = [
            "docker", "exec", "-i", self.container_name,
            "node", "/opt/prime-agent/packages/coding-agent/dist/bundle/cli.js",
            "--mode", "rpc",
            "--provider", self.provider,
            "--model", self.model,
            "--session-dir", "/work/.sessions",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )

        prompt = self._compose_prompt(spec)
        proc.stdin.write((json.dumps({"id": "obj-1", "type": "prompt", "message": prompt}) + "\n").encode())
        await proc.stdin.drain()

        try:
            async for event in self._read_events(proc, spec.max_wall_clock_seconds):
                etype = event.get("type")

                if etype == "session":
                    runtime_session_id = event.get("id")
                if etype == "tool_execution_start":
                    tool_calls += 1
                    self.state = SessionState.WAITING_FOR_CAPABILITY
                if etype == "tool_execution_end":
                    self.state = SessionState.RUNNING
                    if event.get("isError"):
                        tool_err += 1
                    else:
                        tool_ok += 1
                if etype == "agent_end":
                    final_answer = self._extract_final_text(event)
                if etype in ("auto_retry_start", "auto_retry_end"):
                    provider_error = event.get("errorMessage") or event.get("finalError") or provider_error

                mapped = _EVENT_MAP.get(etype)
                if mapped:
                    events.append(
                        RuntimeEvent(type=mapped, at=_utcnow_iso(), detail=self._event_detail(event))
                    )
                if etype == "agent_end":
                    break
        except TimeoutError as e:
            failure = str(e)
        finally:
            with_timeout = proc.wait()
            try:
                await asyncio.wait_for(with_timeout, timeout=10.0)
            except asyncio.TimeoutError:
                proc.kill()

        # Success is asserted from EFFECTS, never from the exit code. An agent
        # that produced no tool executions did nothing, whatever it reported.
        if failure:
            state = SessionState.FAILED
        elif tool_calls == 0:
            state = SessionState.FAILED
            failure = "runtime produced no kernel tool executions — it did nothing"
            if provider_error:
                failure += f" (provider error: {provider_error[:300]})"
        elif tool_ok == 0:
            # Every attempt errored. The agent will still produce a fluent
            # final answer explaining why it could not proceed, and taking that
            # at face value is how a broken environment gets recorded as a
            # completed mission.
            state = SessionState.FAILED
            failure = f"all {tool_err} kernel tool executions failed — the runtime could not act"
            if provider_error:
                failure += f" (provider error: {provider_error[:300]})"
        elif not final_answer:
            state = SessionState.FAILED
            failure = "runtime ended without producing a final answer"
        else:
            state = SessionState.COMPLETED

        self.state = state
        return SessionOutcome(
            state=state,
            final_answer=final_answer,
            events=events,
            tool_execution_count=tool_calls,
            tool_success_count=tool_ok,
            tool_error_count=tool_err,
            failure_reason=failure,
            runtime_session_id=runtime_session_id,
        )

    async def _read_events(self, proc, timeout_seconds: float) -> AsyncIterator[Dict[str, Any]]:
        """Strict JSONL: split on \\n only.

        Prime Agent's RPC docs call out that generic line readers are not
        protocol-compliant because they also split on U+2028/U+2029, which are
        legal inside JSON strings. asyncio's readline splits on \\n only, which
        is correct — but the limit must be raised, since a single event can
        carry a large tool result.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        proc.stdout._limit = 8 * 1024 * 1024  # noqa: SLF001 - large single events

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"runtime exceeded {timeout_seconds}s wall clock")
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                raise TimeoutError(f"runtime exceeded {timeout_seconds}s wall clock")
            if not line:
                return
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError:
                logger.debug("non-JSON line from runtime", extra={"line": text[:200]})

    def _compose_prompt(self, spec: AgentSessionSpec) -> str:
        caps = ", ".join(spec.allowed_capabilities) or "(none)"
        return (
            f"{spec.objective}\n\n"
            f"Success criteria: {spec.success_criteria}\n\n"
            "You are a worker inside an ADOS mission. Your workspace is /work.\n"
            "When the mission requires an action in the organization's systems, use the "
            "ADOS skill — it is the only sanctioned route and the only one that is audited:\n\n"
            "    import ados\n"
            "    caps = await ados.capabilities()\n"
            "    result = await ados.run_capability('<Capability>', {...})\n\n"
            f"This mission grants: {caps}\n"
            "ADOS decides what is permitted; a denial is final, so report it rather than "
            "looking for another route.\n"
        )

    @staticmethod
    def _extract_final_text(agent_end: Dict[str, Any]) -> Optional[str]:
        for message in reversed(agent_end.get("messages", []) or []):
            if message.get("role") != "assistant":
                continue
            parts = [b.get("text", "") for b in (message.get("content") or []) if b.get("type") == "text"]
            text = "\n".join(p for p in parts if p).strip()
            if text:
                return text
        return None

    @staticmethod
    def _event_detail(event: Dict[str, Any]) -> Dict[str, Any]:
        """Small, structured detail — never the whole event. Tool results can
        be megabytes and would bloat the mission's evidence trail."""
        keep = ("id", "toolName", "toolCallId", "isError")
        detail = {k: event[k] for k in keep if k in event}
        if event.get("type") == "tool_execution_start":
            # The code the model actually ran. Every runtime failure so far has
            # been diagnosable only from this, and three of them cost a
            # container teardown to recover it — the workspace is disposable, so
            # if ADOS does not record the code, it is gone. Truncated, because
            # this is an audit trail, not a transcript.
            code = (event.get("args") or {}).get("code")
            if code:
                detail["code"] = str(code)[:600]
        if event.get("type") == "tool_execution_end":
            detail["result_preview"] = str(event.get("result"))[:500]
            # Size of what the tool handed back to the MODEL, which is what
            # actually lands in the next turn's prompt. A capability returning
            # a large payload is charged to context on every subsequent turn.
            detail["result_chars"] = len(str(event.get("result") or ""))
        if event.get("type") == "message_end":
            usage = (event.get("message") or {}).get("usage") or {}
            if usage:
                # cacheRead is kept deliberately: a provider that does not cache
                # prompts re-sends and re-bills the entire context every turn,
                # and cacheRead == 0 across a whole run is the evidence for it.
                detail["usage"] = {
                    k: usage.get(k)
                    for k in ("input", "output", "cacheRead", "cacheWrite", "totalTokens")
                }
        for key in ("errorMessage", "finalError"):
            if event.get(key):
                detail[key] = str(event[key])[:300]
        return detail

    async def teardown(self) -> None:
        """Always runs. The workspace is disposable by design, so anything
        worth keeping must already have been copied into ADOS."""
        if self.container_name:
            await _run("docker", "rm", "-f", self.container_name, timeout=60.0)
            logger.info("Runtime container removed", extra={"container": self.container_name})
        if self.workspace and self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)
        self.state = SessionState.TORN_DOWN


def mint_session_token() -> str:
    """32 bytes of entropy. Opaque and identity-only — it names a session row
    and carries no claims, so nothing the container holds can be decoded or
    widened into a larger grant."""
    return secrets.token_urlsafe(32)
