"""
P11 — admission control for `IntegrationHub.invoke()`, the one place every
capability call in this system reaches a connector (see hub.py's own
docstring). Nothing bounded concurrency before this: `orchestrate/
agent_runner.py`'s single `asyncio.Lock` is a correctness lock for two
agents' shared mutable state, not a resource ceiling, and `db/engine.py`
uses `NullPool` deliberately — no pool ceiling either. Doc 18
(docs/prime-agent-integration/18-production-readiness-review.md) names this
exact gap.

WHY PER-INSTANCE, NOT A MODULE-LEVEL SINGLETON
-------------------------------------------------
~800 tests construct their own `IntegrationHub()`/`default_hub()` instances
constantly. A module-level admission-control singleton would leak
concurrency state across unrelated tests — a test that fails to release a
slot (or is still holding one when the next test starts) would silently
throttle every test after it. `IntegrationHub.__init__` builds its own
`AdmissionControl`, mirroring how it already builds its own
`ConnectorPolicyEngine`.

WHY THIS IS SAFE UNDER REAL CONCURRENCY WITHOUT A LOCK
---------------------------------------------------------
`try_acquire_*` is synchronous and contains no `await`. Under Python's
cooperative single-threaded event loop, a function with no await point
cannot be interleaved with another coroutine mid-execution — the
check-then-increment here is therefore atomic with respect to every other
task on the same loop, the same property every other in-process counter in
this codebase (e.g. RuntimeSessionRow.capability_request_count's read-then-
write inside one open transaction) relies on. This does NOT extend across
processes — see the scope-boundary paragraph in
docs/prime-agent-integration/19-metrics-and-alerting.md: this is
single-process admission control, matching Model A's single-process
envelope.
"""

from __future__ import annotations

DEFAULT_MAX_CONCURRENT_CAPABILITY_EXECUTIONS = 10
DEFAULT_MAX_CONCURRENT_MISSIONS = 3


class AdmissionControl:
    def __init__(
        self,
        *,
        max_concurrent_capability_executions: int = DEFAULT_MAX_CONCURRENT_CAPABILITY_EXECUTIONS,
        max_concurrent_missions: int = DEFAULT_MAX_CONCURRENT_MISSIONS,
    ):
        self._max_capability = max_concurrent_capability_executions
        self._max_missions = max_concurrent_missions
        self._current_capability = 0
        self._current_missions = 0

    def try_acquire_capability_slot(self) -> bool:
        if self._current_capability >= self._max_capability:
            return False
        self._current_capability += 1
        return True

    def release_capability_slot(self) -> None:
        self._current_capability = max(0, self._current_capability - 1)

    def try_acquire_mission_slot(self) -> bool:
        if self._current_missions >= self._max_missions:
            return False
        self._current_missions += 1
        return True

    def release_mission_slot(self) -> None:
        self._current_missions = max(0, self._current_missions - 1)

    @property
    def current_capability_executions(self) -> int:
        """Diagnostics/tests only — never consulted by the gate logic above,
        which always reads `self._current_capability` directly."""
        return self._current_capability

    @property
    def current_missions(self) -> int:
        return self._current_missions
