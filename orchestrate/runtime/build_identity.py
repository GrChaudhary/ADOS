"""
Build identity — lets a caller mechanically establish whether the gateway
process actually answering a request is running the source revision the
caller intends to test.

THE PROBLEM
-----------
uvicorn, run without `--reload` (as this project always runs it), imports
the application once at process start and serves that code forever. If HEAD
moves after the process started — a commit, a checkout, a `git pull` — the
running process keeps serving what it already loaded. Nothing reported that
before this module; the check was "compare `ps` start time to `git log -1`"
by hand, and a stale process had already reached a live verification run
more than once (see docs/prime-agent-integration/14-known-limitations.md).

THE MECHANISM
--------------
A build's identity is the git commit its source tree was checked out at,
plus whether that tree carried uncommitted changes to tracked files at the
moment the identity was computed — the same two facts `git describe --dirty`
reports, computed independently here so it doesn't depend on `git describe`
existing on every PATH this runs on.

It is computed from the actual `.git` metadata on disk, not from an
environment variable (a deployment step can set an env var to any string
irrespective of what code is actually checked out — the exact failure mode
this exists to close) and never from a caller-supplied value (an endpoint
that let a caller assert its own commit would let a stale process simply be
told it is current, which defeats the entire point).

For the running process, it is computed exactly once, at import time — the
instant uvicorn loads this module is the instant "the code it imported at
start" becomes fixed, so that is the earliest and only correct point to read
it. See CURRENT_BUILD_REVISION.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("ados.build_identity")

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class BuildRevision:
    commit: str   # 40-char git SHA, or "unknown" if it could not be determined
    dirty: bool   # True if tracked files differed from `commit` when computed
    source: str   # where this came from (a repo path, or a gateway URL) — diagnostics only

    @property
    def label(self) -> str:
        """The canonical string "expected == actual" compares against."""
        if self.commit == "unknown":
            return "unknown"
        return f"{self.commit}+dirty" if self.dirty else self.commit

    def to_dict(self) -> dict:
        return {"commit": self.commit, "dirty": self.dirty, "label": self.label}


def _run_git(repo_root: Path, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def compute_build_revision(repo_root: Path = REPO_ROOT, *, source: Optional[str] = None) -> BuildRevision:
    """Reads `.git` metadata under `repo_root` right now.

    Production calls this once, at import time, against the real REPO_ROOT
    and freezes the result (CURRENT_BUILD_REVISION below). Tests call it
    directly against other real checkouts — e.g. two `git worktree` trees
    pinned to two different commits — to get two genuinely distinct,
    independently-computed identities without needing two running gateway
    processes.
    """
    label = source or str(repo_root)
    commit = _run_git(repo_root, "rev-parse", "HEAD")
    if not commit:
        return BuildRevision(commit="unknown", dirty=False, source=label)
    # `--untracked-files=no` deliberately excludes untracked files from the
    # dirty determination, matching `git describe --dirty`'s own definition:
    # it answers "does the running code differ from what this commit would
    # check out", not "is the working directory perfectly clean". This repo
    # routinely carries untracked scratch files that have no bearing on what
    # backend/app/main.py actually imported.
    status = _run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
    dirty = bool(status)
    return BuildRevision(commit=commit, dirty=dirty, source=label)


# Computed once, at import time. Do not recompute this per-request — a
# per-request `git rev-parse` would report the CURRENT repository state, not
# the state actually loaded into this process's memory, which is precisely
# the distinction this module exists to preserve.
CURRENT_BUILD_REVISION = compute_build_revision(REPO_ROOT, source="running-process")


class StaleGatewayError(RuntimeError):
    """Raised when a runner's expected source revision does not match the
    build revision actually reported by the running gateway."""


def verify_build_matches(expected: BuildRevision, actual: BuildRevision) -> None:
    """The one comparison this module exists for.

    Raises with a diagnostic naming both sides if they differ. An "unknown"
    actual (git unavailable, not a repo, etc.) is treated as a mismatch, not
    a pass — a build whose identity cannot be established is not a verified
    one, and letting "unknown" satisfy the check would be exactly the
    permissive fallback this exists to prevent.
    """
    if expected.label != "unknown" and expected.label == actual.label:
        return
    # P10: the single raise site for every drift check in this module
    # (mission start, the capability-execution path, and an external
    # runner comparing a remote gateway) — one log line here covers all of
    # them. Commit labels only, never a token or any request content.
    logger.warning(
        "Build identity mismatch detected — refusing to proceed",
        extra={"expected": expected.label, "actual": actual.label, "actual_source": actual.source},
    )
    from backend.app.metrics import build_identity_drift_refusals_total
    build_identity_drift_refusals_total.inc()
    raise StaleGatewayError(
        "gateway build revision does not match the expected source revision — "
        "the running process is not serving the code under test.\n"
        f"  expected: {expected.label}  (from {expected.source})\n"
        f"  actual:   {actual.label}  (from {actual.source})\n"
        "Restart the gateway from the expected revision before proceeding. "
        "This check will not guess, retry, or restart it for you."
    )


def verify_no_drift_since_process_start(repo_root: Path = REPO_ROOT) -> None:
    """The operational form of the P7-B check — not a caller comparing a
    remote gateway against an expected revision, but this same process
    checking itself right before it is about to do something with a real
    external effect (start a mission, which may go on to execute a governed
    capability).

    `CURRENT_BUILD_REVISION` was frozen at import time. If the repository has
    moved since — a commit landed, a checkout happened — while this process
    kept running on `uvicorn` without `--reload`, this process is now stale
    relative to its own source tree, and a mission started from here would
    run under code nobody currently believes is what is deployed. Refusing
    here happens before `MissionRow`/`RuntimeSessionRow` are created, before
    the container starts, before any capability request can reach a
    connector — i.e. before any external effect.

    A no-op when `CURRENT_BUILD_REVISION.commit == "unknown"` — a production
    image built without `.git` (see the Dockerfile's `.dockerignore`) has
    nothing to compare against, and refusing every mission in that
    environment would be a functional regression this check has no business
    causing. This is exactly the environment P7-B's own `.dockerignore`
    finding already described; nothing here changes that trade-off, only
    reuses it.
    """
    if CURRENT_BUILD_REVISION.commit == "unknown":
        return
    current_repo_state = compute_build_revision(repo_root, source="repository-now")
    verify_build_matches(current_repo_state, CURRENT_BUILD_REVISION)


def fetch_gateway_build_revision(
    base_url: str, *, timeout: float = 5.0, client: Optional[httpx.Client] = None
) -> BuildRevision:
    """Asks a running gateway what it reports as its own build identity, via
    the same /healthz endpoint any health check already calls. No new
    authenticated surface, and nothing here lets a caller supply the answer:
    the value comes only from the gateway's own response body, computed by
    that process at its own import time.

    `client` is accepted so tests can pass FastAPI's TestClient (itself an
    httpx.Client subclass running the real app in-process) instead of a real
    socket — the comparison and parsing logic under test is identical either
    way; only the transport changes. `timeout` is only meaningful for the
    real-socket path: TestClient manages its own and warns if overridden.
    """
    if client is not None:
        response = client.get(f"{base_url.rstrip('/')}/healthz")
    else:
        response = httpx.get(f"{base_url.rstrip('/')}/healthz", timeout=timeout)
    response.raise_for_status()
    build = response.json().get("build") or {}
    commit = build.get("commit", "unknown")
    dirty = bool(build.get("dirty", False))
    return BuildRevision(commit=commit, dirty=dirty, source=f"gateway:{base_url}")


def verify_gateway_matches_source(
    base_url: str, repo_root: Path = REPO_ROOT, *, client: Optional[httpx.Client] = None
) -> BuildRevision:
    """The runner/startup-path entry point: fetch what the gateway at
    `base_url` reports, compare it against the source tree at `repo_root`
    right now, and raise StaleGatewayError before returning if they differ.
    Returns the actual (gateway-reported) revision on success, so a caller
    can log/print what it verified.
    """
    expected = compute_build_revision(repo_root, source=f"expected-source:{repo_root}")
    actual = fetch_gateway_build_revision(base_url, client=client)
    verify_build_matches(expected, actual)
    return actual
