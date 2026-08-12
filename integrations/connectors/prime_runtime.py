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
        from orchestrate.runtime.build_identity import verify_no_drift_since_process_start
        from orchestrate.runtime.prime import (
            PrimeAgentRuntime,
            mint_session_token,
            token_expiry,
        )

        # First action, before any row is created: this process's own build
        # identity, frozen at import time, must still match what the
        # repository holds right now. `uvicorn` runs without `--reload`, so a
        # commit landing after this process started would otherwise run
        # under stale code for the whole lifetime of the mission this call is
        # about to create — including any governed capability it goes on to
        # request. See orchestrate/runtime/build_identity.py. Raises
        # StaleGatewayError (a RuntimeError), caught by execute()'s existing
        # broad except and surfaced as a normal FAILED response — no new
        # error-handling path needed.
        verify_no_drift_since_process_start()

        wall_clock = float(
            call.input.get("max_wall_clock_seconds", DEFAULT_WALL_CLOCK_SECONDS)
        )

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
                mission_id=mission.mission_id,
                state="starting",
                token_hash=hash_token(token),
                # Set here rather than left NULL: state alone cannot revoke a
                # credential if the process that writes state dies. See
                # orchestrate/runtime/prime.py:token_expiry.
                token_expires_at=token_expiry(wall_clock),
            )
            db.add(session)
            await db.commit()
            mission_id, session_id = mission.mission_id, session.session_id
            # P10: the only place a mission's own start was visible before
            # this was a row in the database — nothing an operator watching
            # structured logs would see. Domain only, never the objective
            # (agent/caller-authored free text) or the token.
            logger.info(
                "Prime Agent mission started",
                extra={"mission_id": str(mission_id), "session_id": str(session_id), "domain": str(call.input.get("domain", "general"))},
            )
            from backend.app.metrics import missions_started_total
            missions_started_total.inc()
            objective = mission.objective

        spec = AgentSessionSpec(
            mission_id=str(mission_id),
            session_id=str(session_id),
            objective=objective,
            allowed_capabilities=[],
            workspace_files={},
            max_wall_clock_seconds=wall_clock,
        )

        runtime = PrimeAgentRuntime(
            mcp_url=self.mcp_url,
            provider=self.provider,
            model=self.model,
            provider_key_env=self.provider_key_env,
            provider_key=self.provider_key,
            models_json=self.models_json,
        )
        # WHY THE TERMINAL STATE IS WRITTEN IN A `finally`
        # ------------------------------------------------
        # It used to be written after `run_objective` returned, with only the
        # teardown in the `finally`. So on every failure path — the objective
        # raising, the container dying, the ADOS process being killed — the
        # container was destroyed while the session row stayed at `running`.
        # `mcp_gateway._resolve_session` treats `running` as live, so that row
        # was a permanently valid credential for a session that no longer
        # existed. Found by P6-C while testing the states the gateway refuses.
        #
        # `outcome` and `failure` are captured rather than returned into the
        # finalizer so there is ONE writer of the terminal state for both
        # paths; a second write site is how the first one drifted.
        outcome = None
        failure: Optional[BaseException] = None
        try:
            await runtime.start(spec, token)
            async with async_session_factory() as db:
                row = await db.get(RuntimeSessionRow, session_id)
                row.state = "running"
                row.container_name = runtime.container_name
                row.workspace_path = str(runtime.workspace)
                await db.commit()

            outcome = await runtime.run_objective(spec)
            return outcome, session_id
        except BaseException as exc:
            # BaseException, not Exception: a cancelled mission (CancelledError)
            # or an interrupted process leaves exactly the same dangling
            # credential, and is if anything the likelier way to get one.
            failure = exc
            raise
        finally:
            # Teardown first, so what it could not remove is recorded on the
            # row in the same write as the terminal state. `teardown()` is
            # contractually non-raising, and this catches it anyway: the whole
            # point of this block is that the row gets closed, and inheriting a
            # future teardown bug would put the dangling credential straight
            # back. A guard whose correctness depends on another function
            # keeping its promise is not a guard.
            try:
                leftovers = await runtime.teardown()
            except BaseException as exc:  # noqa: BLE001 — see above
                logger.exception("Runtime teardown raised", extra={"session_id": str(session_id)})
                leftovers = [f"teardown raised {type(exc).__name__}: {exc}"]
            await _finalize_session(
                session_id, mission_id,
                outcome=outcome, failure=failure, leftovers=leftovers,
            )


async def _finalize_session(
    session_id,
    mission_id,
    *,
    outcome=None,
    failure: Optional[BaseException] = None,
    leftovers: Optional[list] = None,
) -> None:
    """Write the session's terminal state. Never raises.

    Runs from a `finally`, so raising here would replace the real failure with
    a database error and hide what actually went wrong. It logs instead — and
    the log is the only remaining signal that a row may still be live, which is
    why it is an exception-level log rather than a warning.

    A session that reaches here with neither an outcome nor an exception ended
    in a way this code does not model. It is still closed, and closed as
    `failed`: leaving it `running` would be inventing the more permissive of
    two answers about a credential.
    """
    from db.engine import async_session_factory
    from db.models.mission import MissionRow, RuntimeSessionRow

    orphan_note = (
        "; ".join(f"orphaned {item}" for item in leftovers) if leftovers else None
    )

    try:
        async with async_session_factory() as db:
            row = await db.get(RuntimeSessionRow, session_id)
            mission = await db.get(MissionRow, mission_id)
            if row is None:
                return

            if failure is not None:
                row.state = "failed"
                reason = f"{type(failure).__name__}: {failure}"
            elif outcome is not None:
                row.state = outcome.state.value
                row.tool_execution_count = outcome.tool_execution_count
                row.events = [
                    {"type": e.type, "at": e.at, "detail": e.detail} for e in outcome.events
                ]
                reason = outcome.failure_reason
            else:
                row.state = "failed"
                reason = "session ended without an outcome or an exception"

            row.failure_reason = "; ".join(p for p in (reason, orphan_note) if p) or None

            if mission is not None:
                did_work = bool(outcome is not None and outcome.did_real_work)
                mission.status = "completed" if did_work else "failed"
                mission.result = outcome.final_answer if outcome is not None else None
                mission.failure_reason = row.failure_reason
                from backend.app.metrics import missions_completed_total
                missions_completed_total.labels(outcome=mission.status).inc()

            await db.commit()
    except Exception:  # noqa: BLE001 — see the docstring
        logger.exception(
            "Could not write the terminal state for runtime session %s — the row may "
            "still read as live, and its token with it",
            session_id,
        )


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
