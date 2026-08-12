"""
P11 — integrations/admission_control.py's AdmissionControl in isolation:
below/at/over limit, release semantics, and that it never touches an
asyncio.Lock/await internally (the atomicity argument in its own docstring
rests on that).

Hub-level behavior (rejection before any external side effect, real
concurrent races through IntegrationHub.invoke(), a docker-marked proof a
real container is never started past the mission ceiling) is in
test_integration_hub_admission.py — this file is the smaller-scope unit
underneath it.
"""

from integrations.admission_control import AdmissionControl


def test_below_limit_allowed():
    ac = AdmissionControl(max_concurrent_capability_executions=3, max_concurrent_missions=2)
    assert ac.try_acquire_capability_slot() is True
    assert ac.current_capability_executions == 1


def test_at_limit_last_slot_allowed_deterministically():
    ac = AdmissionControl(max_concurrent_capability_executions=2, max_concurrent_missions=2)
    assert ac.try_acquire_capability_slot() is True
    assert ac.try_acquire_capability_slot() is True
    assert ac.current_capability_executions == 2


def test_over_limit_refused():
    ac = AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1)
    assert ac.try_acquire_capability_slot() is True
    assert ac.try_acquire_capability_slot() is False, "a third slot must not be granted at limit=1 after one acquire"
    assert ac.current_capability_executions == 1, "a refused acquire must not have incremented the counter"


def test_release_frees_a_slot_for_the_next_caller():
    ac = AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1)
    assert ac.try_acquire_capability_slot() is True
    assert ac.try_acquire_capability_slot() is False
    ac.release_capability_slot()
    assert ac.try_acquire_capability_slot() is True


def test_release_below_zero_never_goes_negative():
    """Defensive: a caller that releases without ever having acquired (a bug
    elsewhere) must not corrupt the counter into a negative value that would
    then grant MORE slots than the configured limit."""
    ac = AdmissionControl(max_concurrent_capability_executions=1, max_concurrent_missions=1)
    ac.release_capability_slot()
    ac.release_capability_slot()
    assert ac.current_capability_executions == 0
    assert ac.try_acquire_capability_slot() is True
    assert ac.try_acquire_capability_slot() is False


def test_mission_and_capability_gates_are_independent_counters():
    ac = AdmissionControl(max_concurrent_capability_executions=5, max_concurrent_missions=1)
    assert ac.try_acquire_mission_slot() is True
    assert ac.try_acquire_mission_slot() is False, "mission limit=1 must refuse a second concurrent mission"
    # The general capability ceiling (5) is untouched by mission acquisition —
    # they are deliberately separate counters (see hub.py's invoke()).
    assert ac.try_acquire_capability_slot() is True
    assert ac.current_capability_executions == 1
    assert ac.current_missions == 1


def test_default_limits_match_config_settings_defaults():
    from backend.app.config import Settings

    defaults = Settings()
    ac = AdmissionControl()
    assert ac._max_capability == defaults.max_concurrent_capability_executions
    assert ac._max_missions == defaults.max_concurrent_prime_missions
