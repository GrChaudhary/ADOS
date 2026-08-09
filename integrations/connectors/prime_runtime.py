"""
Prime Agent runtime connector — `RunPrimeRLMAgent` executed for real.

This replaces a facade. `Capability.RUN_PRIME_RLM_AGENT` previously had no
connector at all, so `ConsoleConnector` (which declares `set(Capability)`) won
it and returned `"[console] simulated RunPrimeRLMAgent"` — a green audit row for
an agent that never ran. Separately, `PrimeAgentClient.execute_rlm_task()`
returned a hardcoded "kernel trace" that no code path ever called. Both are
gone; this is the only implementation.

WHAT THIS CAPABILITY DOES, PRECISELY
------------------------------------
Starts a containerized Prime Agent, gives it an objective, lets it reason in its
IPython kernel, and returns what it concluded. **It grants no ADOS capabilities
by default**, so the sub-runtime can compute and reason but cannot act on the
organization. That is the honest scope of an "analysis" capability, and it is
why the grant is empty rather than inherited.

The effect being asserted here is the computation itself, not a change in an
external system. `SUCCEEDED` therefore means the runtime genuinely executed —
observed kernel tool successes and a final answer — and never merely that a
container started or a process exited 0.

NO RECURSION
------------
A Prime Agent session must not be able to spawn another Prime Agent. Subagents
are a product capability that has not been designed, budgeted, or governed, and
arriving at one accidentally through a capability grant would be the worst way
to get it. The gateway stamps `requested_by` as `prime-runtime:mission:<id>`
for every call originating in a runtime, so this connector can recognise its own
kind and refuse. Defence in depth: no mission should grant this capability to a
runtime session in the first place.
"""

import logging
import uuid
from typing import Any, Dict, Optional

from contracts import CallStatus, Capability, CapabilityCall, CapabilityResponse

from .base import Connector

logger = logging.getLogger("ados.integrations.prime_runtime")

#: Prefix the MCP gateway uses for `requested_by` on runtime-originated calls.
#: Matches backend/app/mcp_gateway.py's `f"prime-runtime:mission:{mission_id}"`.
RUNTIME_REQUESTER_PREFIX = "prime-runtime:"

DEFAULT_WALL_CLOCK_SECONDS = 1800.0


class PrimeRuntimeConnector(Connector):
    name = "prime-runtime"
    capabilities = {Capability.RUN_PRIME_RLM_AGENT}

    def __init__(
        self,
        *,
        mcp_url: str = "http://host.docker.internal:8077/mcp/",
        provider: str = "ollama-local",
        model: str = "qwen3-4b-16k:latest",
        provider_key_env: str = "OLLAMA_API_KEY",
        provider_key: str = "ollama",
        models_json: Optional[Dict[str, Any]] = None,
    ):
        self.mcp_url = mcp_url
        self.provider = provider
        self.model = model
        self.provider_key_env = provider_key_env
        self.provider_key = provider_key
        # Defaults to the configuration the acceptance run actually used. A
        # caller wanting a different provider passes its own models_json; see
        # docs/prime-agent-integration/15-provider-benchmark.md for why this is
        # a test configuration rather than an architectural dependency.
        self.models_json = models_json or {
            "providers": {
                "ollama-local": {
                    "baseUrl": "http://host.docker.internal:11434/v1",
                    "api": "openai-completions",
                    "apiKey": "OLLAMA_API_KEY",
                    "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
                    "models": [{"id": "qwen3-4b-16k:latest"}],
                }
            }
        }

    def is_configured(self) -> bool:
        """Docker reachable and the runtime image built.

        Returning False lets the Connector Policy Engine fall back rather than
        fail every call on a machine that has never built the image — but note
        the fallback is ConsoleConnector, which simulates. `_execute` therefore
        never *silently* substitutes a simulation; that decision belongs to the
        policy engine and is visible in the connector name on the audit row.
        """
        import shutil
        import subprocess

        from orchestrate.runtime.prime_image import IMAGE_TAG

        if not shutil.which("docker"):
            return False
        try:
            out = subprocess.run(
                ["docker", "images", "-q", IMAGE_TAG],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.SubprocessError, OSError):
            return False
        return bool(out.stdout.strip())

    async def execute(self, call: CapabilityCall) -> CapabilityResponse:
        requested_by = str(call.requested_by or "")
        if requested_by.startswith(RUNTIME_REQUESTER_PREFIX):
            logger.warning(
                "Refused nested Prime Agent runtime",
                extra={"requested_by": requested_by, "incident_id": call.incident_id},
            )
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=(
                    "a Prime Agent runtime may not start another Prime Agent runtime; "
                    "subagents are not a supported capability"
                ),
            )

        prompt = call.input.get("prompt") or call.input.get("objective")
        if not prompt:
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error="RunPrimeRLMAgent requires a 'prompt' (or 'objective') input",
            )

        try:
            outcome, session_id = await self._run(call, str(prompt))
        except Exception as exc:  # noqa: BLE001 — surfaced as a real failure, never as success
            logger.exception("Prime Agent runtime failed", extra={"incident_id": call.incident_id})
            return CapabilityResponse(
                request_id=call.request_id,
                status=CallStatus.FAILED,
                connector=self.name,
                error=f"{type(exc).__name__}: {exc}",
            )

        return response_for(call, outcome, connector=self.name, session_id=session_id)

    async def _run(self, call: CapabilityCall, prompt: str):
        """Creates the audit rows, runs the container, and tears it down."""
        from db.engine import async_session_factory
        from db.models.mission import MissionRow, RuntimeSessionRow
        from backend.app.mcp_gateway import hash_token
        from orchestrate.runtime.base import AgentSessionSpec
        from orchestrate.runtime.prime import PrimeAgentRuntime, mint_session_token

        async with async_session_factory() as db:
            mission = MissionRow(
                title=f"RunPrimeRLMAgent ({call.input.get('domain', 'general')})",
                objective=prompt,
                domain=str(call.input.get("domain", "general")),
                # EMPTY grant. This capability runs an analysis; it does not
                # hand the organization's action surface to a nested agent.
                allowed_capabilities=[],
                status="running",
                created_by=str(call.requested_by or "system"),
            )
            db.add(mission)
            await db.flush()
            token = mint_session_token()
            session = RuntimeSessionRow(
                mission_id=mission.mission_id, state="starting", token_hash=hash_token(token)
            )
            db.add(session)
            await db.commit()
            mission_id, session_id = mission.mission_id, session.session_id
            objective = mission.objective

        spec = AgentSessionSpec(
            mission_id=str(mission_id),
            session_id=str(session_id),
            objective=objective,
            allowed_capabilities=[],
            workspace_files={},
            max_wall_clock_seconds=float(
                call.input.get("max_wall_clock_seconds", DEFAULT_WALL_CLOCK_SECONDS)
            ),
        )

        runtime = PrimeAgentRuntime(
            mcp_url=self.mcp_url,
            provider=self.provider,
            model=self.model,
            provider_key_env=self.provider_key_env,
            provider_key=self.provider_key,
            models_json=self.models_json,
        )
        try:
            await runtime.start(spec, token)
            async with async_session_factory() as db:
                row = await db.get(RuntimeSessionRow, session_id)
                row.state = "running"
                row.container_name = runtime.container_name
                row.workspace_path = str(runtime.workspace)
                await db.commit()

            outcome = await runtime.run_objective(spec)

            async with async_session_factory() as db:
                row = await db.get(RuntimeSessionRow, session_id)
                row.state = outcome.state.value
                row.tool_execution_count = outcome.tool_execution_count
                row.failure_reason = outcome.failure_reason
                row.events = [
                    {"type": e.type, "at": e.at, "detail": e.detail} for e in outcome.events
                ]
                mission = await db.get(MissionRow, mission_id)
                mission.status = "completed" if outcome.did_real_work else "failed"
                mission.result = outcome.final_answer
                mission.failure_reason = outcome.failure_reason
                await db.commit()
            return outcome, session_id
        finally:
            await runtime.teardown()


def response_for(call: CapabilityCall, outcome, *, connector: str, session_id) -> CapabilityResponse:
    """Maps an observed `SessionOutcome` onto a capability response.

    Separated from `execute` so the decision is testable without Docker — the
    part worth testing is *what counts as success*, not container plumbing.

    Success requires observed effects. A runtime that attempted tool calls and
    had every one of them fail did not do the work, however fluent its final
    answer; that exact situation produced a confident fabricated root cause
    earlier in this integration's history.
    """
    from orchestrate.runtime.base import SessionState

    observed = {
        "runtime_session_id": str(session_id),
        "session_state": outcome.state.value,
        "tool_executions": outcome.tool_execution_count,
        "tool_successes": outcome.tool_success_count,
        "tool_errors": outcome.tool_error_count,
    }

    if outcome.state is not SessionState.COMPLETED or not outcome.did_real_work:
        return CapabilityResponse(
            request_id=call.request_id,
            status=CallStatus.FAILED,
            connector=connector,
            output=observed,
            error=outcome.failure_reason or "the runtime produced no successful kernel execution",
        )

    return CapabilityResponse(
        request_id=call.request_id,
        status=CallStatus.SUCCEEDED,
        connector=connector,
        # The agent's answer is returned as DATA for a caller to read. It is not
        # what made this SUCCEEDED — the observed counts above are.
        output={**observed, "answer": outcome.final_answer},
    )
