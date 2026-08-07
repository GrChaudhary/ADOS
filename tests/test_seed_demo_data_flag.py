"""
SEED_DEMO_DATA gate (backend/app/config.py, backend/app/main.py,
backend/app/routers/memory.py).

executive/seed_data.py's 220 fabricated manufacturing incidents used to load
unconditionally at every startup, so a fresh deployment's dashboards, KPIs,
and Decision Memory opened full of incidents that never happened. These tests
pin the new default and the two seeding paths it gates.

Note the conftest interaction: the repo-root conftest.py forces
SEED_DEMO_DATA=true for the whole suite (the existing tests were written
against a seeded world), so `settings.seed_demo_data` is True while these run.
That's exactly why the default is asserted against a freshly constructed
Settings with the variable removed, rather than against the live singleton.
"""

import os

import pytest

from backend.app.config import Settings
from executive.seed_data import INCIDENT_RECORDS_SEED
from knowledge import DecisionMemoryIndex
from orchestrate.audit_trail import AuditTrail


def test_the_product_default_is_off():
    """A deployment that says nothing about seeding gets no fake incidents."""
    saved = os.environ.pop("SEED_DEMO_DATA", None)
    try:
        assert Settings(_env_file=None).seed_demo_data is False
    finally:
        if saved is not None:
            os.environ["SEED_DEMO_DATA"] = saved


@pytest.mark.parametrize("value", ["true", "1", "yes"])
def test_the_flag_is_readable_from_the_environment(value):
    assert Settings(_env_file=None, SEED_DEMO_DATA=value).seed_demo_data is True


def test_decision_memory_starts_empty_when_seeding_is_off():
    """backend/app/routers/memory.py passes [] rather than None when the flag
    is off. The distinction matters: DecisionMemoryIndex(None) self-seeds from
    executive/seed_data.py, so passing None would silently keep the old
    behaviour."""
    assert DecisionMemoryIndex([])._records == []


def test_decision_memory_self_seeds_when_seeding_is_on():
    assert len(DecisionMemoryIndex(None)._records) == len(INCIDENT_RECORDS_SEED)


def test_audit_trail_starts_empty_when_seeding_is_off():
    """The same None-vs-empty distinction on the orchestrator side: main.py
    passes seed_records=None when the flag is off, and AuditTrail treats that
    as an empty history rather than a request to seed."""
    assert AuditTrail(seed_records=None).all() == []


def test_audit_trail_carries_the_seed_when_seeding_is_on():
    trail = AuditTrail(seed_records=INCIDENT_RECORDS_SEED)
    assert len(trail.all()) == len(INCIDENT_RECORDS_SEED)


def test_seed_ids_never_collide_with_real_incident_ids():
    """main.py's comment claims the two namespaces can't collide, which is
    what makes flipping the flag safe on a deployment that already has real
    history. Real incidents get UUIDs; seeded ones are INC-2026-*."""
    assert all(r.incident_id.startswith("INC-") for r in INCIDENT_RECORDS_SEED)
