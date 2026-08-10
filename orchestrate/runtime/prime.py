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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from .base import AgentSessionSpec, RuntimeEvent, SessionOutcome, SessionState
from .egress import Destination, EgressBoundary, build_allowlist, remove_quietly
from .prime_image import IMAGE_TAG

logger = logging.getLogger("ados.runtime.prime")

# Networking lives in orchestrate/runtime/egress.py. The runtime container now
# sits on a per-session `--internal` Docker network with NO default route and
# no external DNS, reaching exactly two destinations — the ADOS gateway and the
# configured model endpoint — through a destination-pinned relay.
#
# This used to be a shared bridge named `ados-runtime-net` plus
# `--add-host host.docker.internal:host-gateway`, which kept the runtime off
# ADOS's compose network but left it able to reach the whole internet. That was
# placement, not filtering, and was documented as such rather than claimed as
# an allowlist.

_CONTAINER_PREFIX = "ados-prime-"

_ADOS_SKILL_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "infrastructure" / "prime-runtime" / "ados_skill" / "skill_manifest" / "SKILL.md"
)

# Prime Agent's event vocabulary -> ADOS's. Anything unmapped is dropped rather
# than passed through, so ADOS's event stream never depends on upstream shapes.
# NOTE: there is deliberately no "session" entry. Prime Agent's RPC surface
# emits no such event — the mapping used to be here and was dead code, which is
# why runtime_session_id was always NULL. See recover_runtime_session_id().
_EVENT_MAP = {
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

# The kernel's own verdict on a cell. `ipython.d.ts`: status is
# "ok" | "error" | "aborted" | "starting" — "starting" appears only on partial
# `tool_execution_update` results, never on a finished execution.
_KERNEL_OK = "ok"
_KERNEL_FAILED = frozenset({"error", "aborted"})


def classify_tool_execution(event: Dict[str, Any]) -> str:
    """Did this kernel execution actually run? -> "ok" | "error" | "unknown".

    WHY THIS IS NOT `event["isError"]`
    ----------------------------------
    Because `isError` on a finished tool execution does not mean what its name
    says. Prime Agent's core sets it in exactly one place:

        // executePreparedToolCall, dist/bundle/chunk-VNU2AJHD.js
        return { result, isError: false };      // <- hardcoded
        ...
        } catch (error) { ... isError: true }

    So it answers "did the tool function throw?", not "did the code run?". The
    ipython tool computes the real answer — `isError: r.status === "error" ||
    r.status === "aborted"` (dist/core/tools/ipython.js) — puts it on the result
    it returns, and the core then discards it in favour of its own `false`.

    The kernel's verdict survives only in `result.details.status`.

    This was found by an end-to-end run that reported `tools=4 ok=4 err=0` while
    three of the four cells raised `SyntaxError: '(' was never closed`. It
    matters well beyond the counter: `SessionOutcome.did_real_work` is
    `tool_success_count > 0`, and it is the check that catches a runtime which
    could not act and wrote a confident report anyway. Counting dispatches as
    successes made that check blind to the exact failure it exists to catch.

    UNKNOWN, AND WHY IT IS NOT "ok"
    -------------------------------
    A result carrying no verdict is not a success. Prime Agent's throw path
    (`createErrorToolResult`) returns `details: {}` with `isError: true`, which
    is caught above; anything else with no `status` is a shape we do not
    recognise, and the standing invariant is that ADOS never infers success from
    the absence of an error. Unknown executions count toward neither successes
    nor failures, mirroring `CallStatus.UNKNOWN` in the connector layer.

    A future non-kernel agent tool would land here as "unknown" and fail its
    mission loudly. That is deliberate: adding a tool means teaching this
    function how that tool reports failure, rather than inheriting a permissive
    default that silently scores its errors as work done.
    """
    # The tool threw, was aborted, or never dispatched. `details` is `{}` here,
    # so this branch must come first — there is no status to consult.
    if event.get("isError"):
        return "error"

    result = event.get("result")
    if not isinstance(result, dict):
        return "unknown"

    details = result.get("details")
    status = details.get("status") if isinstance(details, dict) else None

    if status == _KERNEL_OK:
        return "ok"
    if status in _KERNEL_FAILED:
        return "error"
    if status is not None:
        return "unknown"  # an upstream status we have not been taught

    # No kernel verdict. The tool's own flag survives on the result object
    # unless a `tool_result` extension hook rewrote it (agent-session.js
    # rebuilds the result without `isError` in that case), so it is worth
    # consulting — but only ever to find a failure, never to claim a success.
    if result.get("isError") is True:
        return "error"
    return "unknown"


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


def _egress_destinations(runtime: "PrimeAgentRuntime") -> List[Destination]:
    """This session's allowlist: the ADOS gateway and the model endpoint."""
    return build_allowlist(
        mcp_url=runtime.mcp_url,
        models_json=runtime.models_json,
        provider=runtime.provider,
    )


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
        self.egress: Optional[EgressBoundary] = None
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

        # The boundary comes up BEFORE the runtime does. Starting the container
        # first and confining it afterwards would leave a window in which
        # model-generated code runs with unrestricted egress.
        self.egress = EgressBoundary(spec.session_id, _egress_destinations(self))
        await self.egress.start()

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
            # Per-session internal network + hosts entries pointing each allowed
            # name at the relay. There is deliberately no host-gateway entry:
            # that is what used to give the runtime a path to the host and to
            # everything else it could route to.
            *self.egress.container_args(),
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
        tool_unknown = 0
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

                if etype == "tool_execution_start":
                    tool_calls += 1
                    self.state = SessionState.WAITING_FOR_CAPABILITY
                if etype == "tool_execution_end":
                    self.state = SessionState.RUNNING
                    verdict = classify_tool_execution(event)
                    if verdict == "ok":
                        tool_ok += 1
                    elif verdict == "error":
                        tool_err += 1
                    else:
                        tool_unknown += 1
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
            # Not one execution actually ran. The agent will still produce a
            # fluent final answer explaining why it could not proceed, and
            # taking that at face value is how a broken environment gets
            # recorded as a completed mission.
            state = SessionState.FAILED
            failure = (
                f"none of {tool_calls} kernel tool executions succeeded "
                f"({tool_err} failed, {tool_unknown} indeterminate) — the runtime could not act"
            )
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
            tool_unknown_count=tool_unknown,
            failure_reason=failure,
            # Read here, while the workspace still exists — teardown deletes it.
            runtime_session_id=runtime_session_id or self.recover_runtime_session_id(),
        )

    def recover_runtime_session_id(self) -> Optional[str]:
        """Prime Agent's own session id, recovered from its session file.

        There is no `session` event on the RPC surface. An earlier design note
        asserted one, on the reasonable assumption that a mode built for
        automation would announce its session id; it does not, and the id is
        reachable over the protocol only by *asking* — the `get_state` command,
        which returns an `RpcSessionState` (`src/modes/rpc/rpc-types.ts`).

        Injecting an extra command into a live RPC stream to learn an
        identifier is more moving parts than the problem deserves. The session
        file's basename IS the id (`src/core/session-file-actions.ts`:
        `sessionId = basename(sessionPath).replace(/\\.jsonl$/, "")`), and Prime
        Agent writes it into `--session-dir`, which is inside our own workspace.
        So this is a read, not a protocol change.

        Timing matters: the workspace is disposable and `teardown()` deletes it,
        so this must run before then — which is why `run_objective` calls it
        rather than `teardown`.

        Most recent file wins: a resumed session directory can hold several, and
        the one this run just wrote is the newest.
        """
        if not self.workspace:
            return None
        sessions = self.workspace / ".sessions"
        try:
            files = [p for p in sessions.glob("*.jsonl") if p.is_file()]
        except OSError:
            return None
        if not files:
            return None
        return max(files, key=lambda p: p.stat().st_mtime).stem

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
            # The kernel's own verdict, recorded explicitly rather than left to
            # be recovered from a truncated preview. `isError` is kept alongside
            # it on purpose: the two disagreeing is the signature of the defect
            # this field exists to make visible, and an audit row that shows
            # only the corrected value hides that history.
            detail["kernel_verdict"] = classify_tool_execution(event)
            result = event.get("result")
            details = result.get("details") if isinstance(result, dict) else None
            if isinstance(details, dict):
                detail["kernel_status"] = details.get("status")
                if details.get("errorEname"):
                    detail["kernel_error"] = str(details["errorEname"])[:120]
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

    async def teardown(self) -> List[str]:
        """Always runs, never raises, and reports what it could not remove.

        The workspace is disposable by design, so anything worth keeping must
        already have been copied into ADOS.

        WHY EVERY STEP IS GUARDED SEPARATELY
        ------------------------------------
        This used to be three bare awaits. `_run` raises `TimeoutError` when a
        docker command does not return in time — which is precisely what a
        wedged daemon does, and the daemon wedging is not hypothetical here: it
        happened mid-run during P6-B. A `TimeoutError` from `docker rm` would
        propagate out of the caller's `finally`, skipping the relay, both
        networks and the workspace, and *replacing* the real failure with a
        timeout. The one moment cleanup matters most was the one moment it
        stopped early.

        So each resource is attempted independently, and what could not be
        removed is returned rather than logged and forgotten — the caller
        records it on the session row so an operator can find the orphans
        later. Returning them is not decoration: nothing else in ADOS knows
        these names once this object is gone.
        """
        leftovers: List[str] = []

        if self.container_name:
            leftovers += await remove_quietly(
                "container", self.container_name,
                "docker", "rm", "-f", self.container_name,
            )
            logger.info("Runtime container removed", extra={"container": self.container_name})

        # After the runtime container, not before: the networks cannot be
        # removed while anything is still attached to them.
        if self.egress:
            try:
                leftovers += await self.egress.teardown()
            except Exception as exc:  # noqa: BLE001 — teardown must not raise
                leftovers.append(f"egress boundary: {type(exc).__name__}: {exc}")

        if self.workspace and self.workspace.exists():
            # ignore_errors=True never raises, but it also never says it
            # failed, so the directory is re-checked rather than assumed gone.
            shutil.rmtree(self.workspace, ignore_errors=True)
            if self.workspace.exists():
                leftovers.append(f"workspace {self.workspace}")

        self.state = SessionState.TORN_DOWN
        if leftovers:
            logger.warning(
                "Runtime teardown left resources behind",
                extra={"container": self.container_name, "leftovers": leftovers},
            )
        return leftovers


def mint_session_token() -> str:
    """32 bytes of entropy. Opaque and identity-only — it names a session row
    and carries no claims, so nothing the container holds can be decoded or
    widened into a larger grant."""
    return secrets.token_urlsafe(32)


# Container start, teardown, and clock skew between ADOS and the database. Not
# a second budget: it exists so a session that uses its FULL wall clock is not
# cut off a few seconds early by its own credential.
TOKEN_GRACE_SECONDS = 300.0


def token_expiry(max_wall_clock_seconds: float, *, now: Optional[datetime] = None) -> datetime:
    """When this session's token stops being accepted.

    The lifetime is the session's own deadline plus a bounded grace, because a
    token that outlives the mission's wall-clock budget is a credential nobody
    is waiting on. `run_objective` abandons the session at
    `max_wall_clock_seconds`; anything presenting the token after that is, by
    definition, not the run ADOS is still tracking.

    WHY THIS EXISTS AT ALL
    ----------------------
    `token_expires_at` was on the row and checked on every capability call from
    the day the gateway was written, and nothing ever set it. P6-C found the
    column defaulting to NULL in every code path, which made the expiry branch
    dead and left session *state* as the only revocation — and state is written
    by ADOS after the fact, so a crashed mission left a permanently valid
    credential (see `PrimeRuntimeConnector._run`, fixed alongside this).

    The two guards are deliberately independent. State revokes promptly but
    only when ADOS is alive to write it; expiry revokes unconditionally but
    only eventually. A dead ADOS process defeats the first and not the second.
    """
    return (now or datetime.now(timezone.utc)) + timedelta(
        seconds=max_wall_clock_seconds + TOKEN_GRACE_SECONDS
    )
