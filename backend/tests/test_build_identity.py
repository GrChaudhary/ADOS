"""
Build identity — proves the gateway can be mechanically checked for staleness
rather than trusted on faith ("I remembered to restart uvicorn").

The two-build fixture below uses `git worktree add` against THIS repository's
own real history: two genuine checkouts, pinned to two genuine, different
commits, each with its own real SHA. That is deliberate rather than the
easier route of fabricating two strings — a fabricated "old commit" would
only prove the comparison operator works, not that the underlying mechanism
(reading `.git` metadata from a real checkout) can actually tell two builds
apart. `git worktree` was chosen over spinning up two full gateway processes
(Docker/uvicorn on two ports) because it is the smallest fixture that still
exercises the real subprocess-based git calls in build_identity.py end to
end; two processes would additionally prove uvicorn's import-once behaviour,
which is a Python/uvicorn property this suite is not in the business of
re-verifying.
"""
import subprocess
from pathlib import Path

import pytest

from orchestrate.runtime import build_identity
from orchestrate.runtime.build_identity import (
    REPO_ROOT,
    CURRENT_BUILD_REVISION,
    StaleGatewayError,
    compute_build_revision,
    fetch_gateway_build_revision,
    verify_build_matches,
    verify_gateway_matches_source,
    verify_no_drift_since_process_start,
)


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture(scope="module")
def two_real_checkouts(tmp_path_factory):
    """Two real `git worktree` checkouts of this repo, pinned to HEAD and to
    HEAD's parent — two genuinely different, independently verifiable commit
    identities, cleaned up afterward regardless of test outcome."""
    head = _git("rev-parse", "HEAD")
    parent = _git("rev-parse", "HEAD~1")
    assert head != parent, "need at least two commits in history for this fixture"

    base = tmp_path_factory.mktemp("build_identity_worktrees")
    dir_a, dir_b = base / "at_head", base / "at_parent"
    _git("worktree", "add", "--detach", str(dir_a), head)
    _git("worktree", "add", "--detach", str(dir_b), parent)
    try:
        yield {"head": (dir_a, head), "parent": (dir_b, parent)}
    finally:
        _git("worktree", "remove", "--force", str(dir_a))
        _git("worktree", "remove", "--force", str(dir_b))


def test_current_build_identity_is_reported_correctly():
    real_head = _git("rev-parse", "HEAD")
    assert CURRENT_BUILD_REVISION.commit == real_head
    assert CURRENT_BUILD_REVISION.label.startswith(real_head)


def test_two_real_checkouts_produce_two_distinct_verifiable_identities(two_real_checkouts):
    (dir_a, commit_a), (dir_b, commit_b) = two_real_checkouts["head"], two_real_checkouts["parent"]

    rev_a = compute_build_revision(dir_a, source="checkout-a")
    rev_b = compute_build_revision(dir_b, source="checkout-b")

    assert rev_a.commit == commit_a
    assert rev_b.commit == commit_b
    assert rev_a.commit != rev_b.commit
    assert rev_a.label != rev_b.label
    assert rev_a.dirty is False and rev_b.dirty is False  # fresh worktrees, nothing edited


def test_expected_not_equal_actual_raises_stale_gateway_error(two_real_checkouts):
    (dir_a, commit_a), (dir_b, commit_b) = two_real_checkouts["head"], two_real_checkouts["parent"]
    expected = compute_build_revision(dir_a, source="expected")
    stale_actual = compute_build_revision(dir_b, source="actual-gateway")

    with pytest.raises(StaleGatewayError) as excinfo:
        verify_build_matches(expected, stale_actual)

    message = str(excinfo.value)
    assert commit_a in message
    assert commit_b in message


def test_matching_expected_and_actual_passes(two_real_checkouts):
    dir_a, commit_a = two_real_checkouts["head"]
    expected = compute_build_revision(dir_a, source="expected")
    actual = compute_build_revision(dir_a, source="actual-gateway")

    verify_build_matches(expected, actual)  # must not raise


def test_unknown_identity_never_satisfies_the_check(tmp_path):
    not_a_repo = tmp_path / "not_a_git_repo"
    not_a_repo.mkdir()
    unknown = compute_build_revision(not_a_repo, source="not-a-repo")

    assert unknown.commit == "unknown"
    assert unknown.label == "unknown"
    # Two "unknown" builds are not proof of a match — an unverifiable build
    # must never be treated as verified, even against itself.
    with pytest.raises(StaleGatewayError):
        verify_build_matches(unknown, unknown)


def test_dirty_tracked_changes_are_detected(two_real_checkouts):
    dir_a, commit_a = two_real_checkouts["head"]
    clean = compute_build_revision(dir_a, source="before-edit")
    assert clean.dirty is False

    tracked_file = dir_a / "README.md"
    original = tracked_file.read_text()
    tracked_file.write_text(original + "\n<!-- build-identity test edit -->\n")
    try:
        dirty = compute_build_revision(dir_a, source="after-edit")
        assert dirty.commit == commit_a
        assert dirty.dirty is True
        assert dirty.label == f"{commit_a}+dirty"
        assert dirty.label != clean.label
    finally:
        tracked_file.write_text(original)


def test_healthz_reports_the_real_build_identity_not_a_placeholder(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["build"]["commit"] == CURRENT_BUILD_REVISION.commit
    assert body["build"]["dirty"] == CURRENT_BUILD_REVISION.dirty
    assert body["build"]["label"] == CURRENT_BUILD_REVISION.label


def test_caller_cannot_spoof_the_reported_identity(client):
    """A caller supplying its own idea of the commit — as a query param, as a
    header — must have zero effect. The endpoint reports what the process
    computed at import time, always."""
    spoofed = "0" * 40
    response = client.get(
        "/healthz",
        params={"commit": spoofed, "build": spoofed, "git_sha": spoofed},
        headers={"X-Build-Commit": spoofed, "X-Git-Sha": spoofed},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["build"]["commit"] != spoofed
    assert body["build"]["commit"] == CURRENT_BUILD_REVISION.commit


def test_healthz_leaks_no_secrets_or_tokens(client):
    response = client.get("/healthz")
    body = response.json()
    assert set(body.keys()) == {"status", "env", "event_bus_backend", "build"}
    assert set(body["build"].keys()) == {"commit", "dirty", "label"}
    # A 40-hex-char SHA (or the literal "unknown"), nothing resembling a
    # token, password, or connection string.
    commit = body["build"]["commit"]
    assert commit == "unknown" or (len(commit) == 40 and all(c in "0123456789abcdef" for c in commit))


def test_existing_healthz_behavior_intact(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "env" in body
    assert "event_bus_backend" in body


def test_fetch_gateway_build_revision_reads_only_the_servers_own_report(client):
    """Exercises the real HTTP round trip (in-process ASGI transport, real
    request/response cycle through FastAPI) rather than only the pure
    function — this is the actual mechanism `verify_gateway_matches_source`
    uses against a real gateway."""
    revision = fetch_gateway_build_revision("http://testserver", client=client)
    assert revision.commit == CURRENT_BUILD_REVISION.commit
    assert revision.label == CURRENT_BUILD_REVISION.label


def test_verify_gateway_matches_source_passes_when_repo_root_is_this_repo(client):
    # The running "gateway" here is the real app object, imported from the
    # real REPO_ROOT — expected and actual are the same build by construction.
    actual = verify_gateway_matches_source("http://testserver", REPO_ROOT, client=client)
    assert actual.commit == CURRENT_BUILD_REVISION.commit


def test_verify_gateway_matches_source_fails_against_a_different_real_checkout(
    two_real_checkouts, client
):
    """The operator workflow this whole module exists for: the gateway is
    genuinely running one real build (CURRENT_BUILD_REVISION, served over
    the in-process transport below); the caller expects a DIFFERENT real
    build (the parent-commit worktree). This must be refused."""
    dir_b, commit_b = two_real_checkouts["parent"]
    assert commit_b != CURRENT_BUILD_REVISION.commit

    with pytest.raises(StaleGatewayError):
        verify_gateway_matches_source("http://testserver", dir_b, client=client)


# --- P7-D: the operational (self) drift guard --------------------------------


def test_no_drift_is_silent_when_the_repo_still_matches_the_frozen_identity(monkeypatch):
    same = build_identity.BuildRevision(commit="a" * 40, dirty=False, source="test-frozen")
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", same)
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: build_identity.BuildRevision(commit="a" * 40, dirty=False, source="test-repo-now"),
    )
    verify_no_drift_since_process_start()  # must not raise


def test_drift_since_process_start_raises(monkeypatch):
    frozen = build_identity.BuildRevision(commit="a" * 40, dirty=False, source="test-frozen")
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", frozen)
    monkeypatch.setattr(
        build_identity, "compute_build_revision",
        lambda repo_root, source=None: build_identity.BuildRevision(commit="b" * 40, dirty=False, source="test-repo-now"),
    )
    with pytest.raises(StaleGatewayError) as excinfo:
        verify_no_drift_since_process_start()
    message = str(excinfo.value)
    assert "a" * 40 in message
    assert "b" * 40 in message


def test_drift_check_is_a_no_op_when_the_frozen_identity_is_unknown(monkeypatch):
    """A production image built without .git (see the Dockerfile's
    .dockerignore) freezes CURRENT_BUILD_REVISION as "unknown" at import
    time. Refusing every mission there would be a functional regression,
    not a safety win — there is nothing to compare against."""
    unknown = build_identity.BuildRevision(commit="unknown", dirty=False, source="test-no-git")
    monkeypatch.setattr(build_identity, "CURRENT_BUILD_REVISION", unknown)

    def _must_not_be_called(repo_root, source=None):
        raise AssertionError("compute_build_revision must not be called when the frozen identity is unknown")

    monkeypatch.setattr(build_identity, "compute_build_revision", _must_not_be_called)
    verify_no_drift_since_process_start()  # must not raise, must not shell out to git at all


def test_drift_check_against_the_real_repository_passes_right_now():
    """No mocking: this process's own CURRENT_BUILD_REVISION, checked against
    the real repository state at the moment this test runs. Passes as long
    as nothing has been committed since this test process started — exactly
    the invariant the guard exists to protect in production."""
    verify_no_drift_since_process_start(REPO_ROOT)  # must not raise
