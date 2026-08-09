"""
Regression coverage for `runtime_session_id`.

The field existed on `runtime_sessions` from the start and was **always NULL**.
The adapter listened for a `{"type":"session"}` RPC event on the assumption that
a mode built for automation would announce its session id. Prime Agent emits no
such event — the id is reachable over the protocol only via the `get_state`
command — so the mapping was dead code and ADOS could not correlate its session
row with Prime Agent's own session file after the container was gone.

The fix reads the id from the session file's basename, which is where Prime
Agent puts it (`src/core/session-file-actions.ts`). No Docker needed to test
that: the workspace is an ordinary directory.
"""

import time
from pathlib import Path

import pytest

from orchestrate.runtime.prime import _EVENT_MAP, PrimeAgentRuntime


def _runtime(tmp_path: Path) -> PrimeAgentRuntime:
    runtime = PrimeAgentRuntime(mcp_url="http://example.invalid/mcp/")
    runtime.workspace = tmp_path
    return runtime


def test_the_session_id_is_recovered_from_the_session_file(tmp_path):
    sessions = tmp_path / ".sessions"
    sessions.mkdir()
    (sessions / "019fe6b6-3fd5-7567-9b96-4ddebd691005.jsonl").write_text("{}\n")

    assert _runtime(tmp_path).recover_runtime_session_id() == (
        "019fe6b6-3fd5-7567-9b96-4ddebd691005"
    )


def test_the_newest_session_file_wins(tmp_path):
    """A resumed session directory can hold several; the one this run just
    wrote is the newest."""
    sessions = tmp_path / ".sessions"
    sessions.mkdir()
    old = sessions / "aaaaaaaa-0000-0000-0000-000000000000.jsonl"
    new = sessions / "bbbbbbbb-1111-1111-1111-111111111111.jsonl"
    old.write_text("{}\n")
    time.sleep(0.01)
    new.write_text("{}\n")
    # Make the ordering unambiguous regardless of filesystem timestamp
    # granularity, which on some filesystems is coarser than the write gap.
    import os
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    assert _runtime(tmp_path).recover_runtime_session_id() == (
        "bbbbbbbb-1111-1111-1111-111111111111"
    )


def test_no_session_directory_returns_none_rather_than_raising(tmp_path):
    """A run that died before Prime Agent wrote anything must still produce an
    outcome — a missing id is not a reason to lose the whole record."""
    assert _runtime(tmp_path).recover_runtime_session_id() is None


def test_an_empty_session_directory_returns_none(tmp_path):
    (tmp_path / ".sessions").mkdir()
    assert _runtime(tmp_path).recover_runtime_session_id() is None


def test_no_workspace_returns_none():
    runtime = PrimeAgentRuntime(mcp_url="http://example.invalid/mcp/")
    assert runtime.workspace is None
    assert runtime.recover_runtime_session_id() is None


def test_non_jsonl_files_are_ignored(tmp_path):
    sessions = tmp_path / ".sessions"
    sessions.mkdir()
    (sessions / "notes.txt").write_text("scratch")
    (sessions / "cccccccc-2222-2222-2222-222222222222.jsonl").write_text("{}\n")

    assert _runtime(tmp_path).recover_runtime_session_id() == (
        "cccccccc-2222-2222-2222-222222222222"
    )


def test_the_dead_session_event_mapping_is_gone():
    """Structural. The `session` entry in _EVENT_MAP was the bug: it made the
    adapter look like it captured the id while capturing nothing. If someone
    re-adds it, they should have to justify it against Prime Agent's actual RPC
    surface, which has no such event."""
    assert "session" not in _EVENT_MAP


def test_the_id_must_be_read_before_teardown_deletes_the_workspace(tmp_path):
    """Ordering is the whole risk here. teardown() removes the workspace, so a
    recovery attempted afterwards silently yields None — which is exactly the
    NULL this change exists to fix."""
    sessions = tmp_path / ".sessions"
    sessions.mkdir()
    (sessions / "dddddddd-3333-3333-3333-333333333333.jsonl").write_text("{}\n")
    runtime = _runtime(tmp_path)

    recovered = runtime.recover_runtime_session_id()
    assert recovered == "dddddddd-3333-3333-3333-333333333333"

    import shutil
    shutil.rmtree(tmp_path)
    assert runtime.recover_runtime_session_id() is None
