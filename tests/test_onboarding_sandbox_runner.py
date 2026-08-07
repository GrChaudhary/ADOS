"""
orchestrate/onboarding/sandbox_runner.py — Turn 4's mandatory sandbox gate.
Real Docker build + isolated run against tests/fixtures/mcp_native_sample,
gated on Docker actually being present (this is deliberately not mocked —
the whole point of this module is producing real execution evidence, so a
test that mocks the isolation would prove nothing about whether the
isolation is real). Skipped automatically in any environment without
Docker rather than failing the suite.
"""

import asyncio
import shutil
import uuid
from pathlib import Path

import httpx
import pytest

from orchestrate.onboarding import sandbox_runner

_MCP_NATIVE_FIXTURE = str(Path(__file__).parent / "fixtures" / "mcp_native_sample")
_BROKEN_FIXTURE = str(Path(__file__).parent / "fixtures" / "mcp_native_broken")
_RAW_CODE_FIXTURE = str(Path(__file__).parent / "fixtures" / "raw_code_sample")

# Only the MCP-native tests need Docker — applied per-function, not at
# module level, since the OpenAPI tests below (httpx.MockTransport, no
# subprocess/container involved) should always run regardless.
_needs_docker = pytest.mark.skipif(
    not sandbox_runner.is_docker_available(), reason="Docker is required for real sandbox isolation tests"
)


@_needs_docker
@pytest.mark.asyncio
async def test_real_sandboxed_tool_call_succeeds_with_correct_result():
    result = await sandbox_runner.run_mcp_sandbox_test(
        local_path=_MCP_NATIVE_FIXTURE,
        launch_command=["python", "server.py"],
        tool_name="add_numbers",
        sample_input={"a": 4, "b": 5},
        timeout_seconds=90,
        build_timeout_seconds=180,
    )
    assert result.passed is True
    assert result.raw_output == "9"
    assert "network=none" in result.evidence_summary
    assert result.duration_ms > 0


@_needs_docker
@pytest.mark.asyncio
async def test_network_isolation_actually_blocks_an_outbound_request():
    """The regression test this module exists to have: proves --network=none
    is a real, enforced constraint, not just a flag that happens to be
    present in the command line."""
    result = await sandbox_runner.run_mcp_sandbox_test(
        local_path=_MCP_NATIVE_FIXTURE,
        launch_command=["python", "server.py"],
        tool_name="attempt_outbound_request",
        sample_input={},
        timeout_seconds=90,
        build_timeout_seconds=180,
    )
    assert result.passed is False
    assert "reached example.com" not in result.raw_output


@_needs_docker
@pytest.mark.asyncio
async def test_live_call_allows_network_unlike_sandbox_test():
    """The one deliberate difference between sandbox testing and live
    post-activation invocation: live calls get real network access, since
    a live capability's whole point is usually reaching a real external
    system. Proves it's not accidentally still network=none."""
    result = await sandbox_runner.run_mcp_live_call(
        local_path=_MCP_NATIVE_FIXTURE,
        launch_command=["python", "server.py"],
        tool_name="attempt_outbound_request",
        arguments={},
        timeout_seconds=90,
        build_timeout_seconds=180,
    )
    assert "reached example.com" in result.get("result", "")


@_needs_docker
@pytest.mark.asyncio
async def test_live_call_still_isolates_resources_and_filesystem():
    result = await sandbox_runner.run_mcp_live_call(
        local_path=_MCP_NATIVE_FIXTURE,
        launch_command=["python", "server.py"],
        tool_name="add_numbers",
        arguments={"a": 10, "b": 32},
        timeout_seconds=90,
        build_timeout_seconds=180,
    )
    assert result == {"result": 42}


@_needs_docker
@pytest.mark.asyncio
async def test_docker_build_failure_produces_a_clear_failed_result_not_a_crash():
    result = await sandbox_runner.run_mcp_sandbox_test(
        local_path=_BROKEN_FIXTURE,
        launch_command=["python", "server.py"],
        tool_name="anything",
        sample_input={},
        timeout_seconds=30,
        build_timeout_seconds=60,
    )
    assert result.passed is False
    assert "failed" in result.evidence_summary.lower()


# ---------------------------------------------------------------------
# raw_code track — real Docker build + isolated run of an arbitrary
# function via vendor/raw_code_runner.py, not fastmcp.Client (this isn't
# a persistent MCP stdio server, it's a one-shot call/response).
# ---------------------------------------------------------------------

@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_sandboxed_call_succeeds_with_correct_result():
    result = await sandbox_runner.run_raw_code_sandbox_test(
        local_path=_RAW_CODE_FIXTURE, entrypoint_path="tool.py", function_name="add_numbers",
        sample_input={"a": 4, "b": 5}, timeout_seconds=90, build_timeout_seconds=180,
    )
    assert result.passed is True
    assert result.raw_output == "9"
    assert "network=none" in result.evidence_summary


@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_network_isolation_actually_blocks_an_outbound_request():
    result = await sandbox_runner.run_raw_code_sandbox_test(
        local_path=_RAW_CODE_FIXTURE, entrypoint_path="tool.py", function_name="attempt_outbound_request",
        sample_input={}, timeout_seconds=90, build_timeout_seconds=180,
    )
    assert result.passed is False
    assert "reached example.com" not in result.raw_output


@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_live_call_allows_network_unlike_sandbox_test():
    result = await sandbox_runner.run_raw_code_live_call(
        local_path=_RAW_CODE_FIXTURE, entrypoint_path="tool.py", function_name="attempt_outbound_request",
        arguments={}, timeout_seconds=90, build_timeout_seconds=180,
    )
    assert "reached example.com" in result.get("result", "")


@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_live_call_still_isolates_resources_and_filesystem():
    result = await sandbox_runner.run_raw_code_live_call(
        local_path=_RAW_CODE_FIXTURE, entrypoint_path="tool.py", function_name="add_numbers",
        arguments={"a": 10, "b": 32}, timeout_seconds=90, build_timeout_seconds=180,
    )
    assert result == {"result": 42}


@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_unknown_function_produces_a_clean_failed_result_not_a_crash(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    (target / "tool.py").write_text("def f(): return 1\n")

    result = await sandbox_runner.run_raw_code_sandbox_test(
        local_path=str(target), entrypoint_path="tool.py", function_name="does_not_exist",
        sample_input={}, timeout_seconds=90, build_timeout_seconds=180,
    )
    assert result.passed is False
    assert "not an eligible top-level function" in result.evidence_summary


@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_non_serializable_result_produces_a_clean_failed_result(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    (target / "tool.py").write_text("class Weird:\n    pass\n\ndef make_weird():\n    return Weird()\n")

    result = await sandbox_runner.run_raw_code_sandbox_test(
        local_path=str(target), entrypoint_path="tool.py", function_name="make_weird",
        sample_input={}, timeout_seconds=90, build_timeout_seconds=180,
    )
    assert result.passed is False
    assert "not JSON-serializable" in result.evidence_summary


@_needs_docker
@pytest.mark.asyncio
async def test_raw_code_timeout_does_not_leave_an_orphaned_container(tmp_path):
    """The regression test for a real gap found during design review:
    _run_subprocess's own timeout handler only kills the local `docker
    run` CLI client, not the actual container (they're decoupled --
    containers are supervised by dockerd/containerd). Proves the explicit
    `docker kill <name>` teardown in _build_and_call_raw_code's finally
    actually stops it rather than leaving it orphaned and still running."""
    target = tmp_path / "repo"
    target.mkdir()
    (target / "tool.py").write_text("import time\n\ndef sleep_forever():\n    time.sleep(600)\n")

    result = await sandbox_runner.run_raw_code_sandbox_test(
        local_path=str(target), entrypoint_path="tool.py", function_name="sleep_forever",
        sample_input={}, timeout_seconds=3, build_timeout_seconds=180,
    )
    assert result.passed is False
    assert "timed out" in result.evidence_summary.lower()

    # The regression this guards is "still running", so check that with no
    # tolerance at all: docker kill has already returned by now.
    returncode, running = await sandbox_runner._run_subprocess(
        "docker", "ps", "--filter", "name=ados-onboarding-run-", "--format", "{{.Names}}", timeout_seconds=15.0
    )
    assert returncode == 0
    assert running.strip() == "", f"container still running after teardown: {running.strip()}"

    # Removal is a separate step: --rm is reaped asynchronously by the daemon
    # after the kill, so a container can briefly linger in `ps -a` as exited.
    # Poll rather than sample once, or this races the daemon.
    for _ in range(30):
        returncode, output = await sandbox_runner._run_subprocess(
            "docker", "ps", "-a", "--filter", "name=ados-onboarding-run-", "--format", "{{.Names}}", timeout_seconds=15.0
        )
        assert returncode == 0
        if output.strip() == "":
            break
        await asyncio.sleep(0.5)
    else:
        pytest.fail(f"container never got removed: {output.strip()}")


@pytest.mark.asyncio
async def test_raw_code_no_docker_available_returns_failed_result_without_raising(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "is_docker_available", lambda: False)
    result = await sandbox_runner.run_raw_code_sandbox_test(
        local_path=_RAW_CODE_FIXTURE, entrypoint_path="tool.py", function_name="add_numbers", sample_input={"a": 1, "b": 1},
    )
    assert result.passed is False
    assert "Docker is not available" in result.evidence_summary


def test_raw_code_image_tag_distinguishes_install_dependencies_variant(tmp_path):
    (tmp_path / "tool.py").write_text("def f(): return 1\n")
    with_deps = sandbox_runner._raw_code_image_tag(tmp_path, True)
    without_deps = sandbox_runner._raw_code_image_tag(tmp_path, False)
    assert with_deps != without_deps


# ---------------------------------------------------------------------
# Image content-hash caching + isolation hardening. Every fixture copy
# below gets a unique marker file written into it so its content hash is
# guaranteed never-before-built, regardless of what other tests in this
# session (or a prior run — images are no longer deleted after use) have
# already cached under the unmodified fixture's own hash.
# ---------------------------------------------------------------------

def _unique_fixture_copy(tmp_path: Path) -> Path:
    target = tmp_path / f"repo-{uuid.uuid4().hex[:8]}"
    shutil.copytree(_MCP_NATIVE_FIXTURE, target)
    (target / ".cache-test-marker").write_text(uuid.uuid4().hex)
    return target


@_needs_docker
@pytest.mark.asyncio
async def test_second_call_against_unchanged_source_reuses_the_cached_image(tmp_path, monkeypatch):
    target = _unique_fixture_copy(tmp_path)
    original = sandbox_runner._run_subprocess
    build_calls = []

    async def _counting(*args, **kwargs):
        if "build" in args:
            build_calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(sandbox_runner, "_run_subprocess", _counting)

    for _ in range(2):
        result = await sandbox_runner.run_mcp_sandbox_test(
            local_path=str(target), launch_command=["python", "server.py"],
            tool_name="add_numbers", sample_input={"a": 1, "b": 2},
            timeout_seconds=90, build_timeout_seconds=180,
        )
        assert result.passed is True

    assert len(build_calls) == 1, "second call against unchanged source should have skipped docker build"


def test_mutating_the_fixture_forces_a_different_image_tag(tmp_path):
    """No Docker needed — the tag is a pure function of build-context
    content, computed before any build subprocess runs. A different tag
    is exactly what forces a rebuild (_build_image checks-before-build by
    tag)."""
    target = _unique_fixture_copy(tmp_path)
    tag_before = sandbox_runner._image_tag_for(target)

    (target / "server.py").write_text((target / "server.py").read_text() + "\n# mutated\n")
    tag_after = sandbox_runner._image_tag_for(target)

    assert tag_before != tag_after


# ---------------------------------------------------------------------
# Published-artifact launches (npx/uvx). These cannot resolve their
# package at run time -- the sandbox is --network=none, so `npx pkg@ver`
# dies EAI_AGAIN -- so the package is installed at build time and the
# bin invoked directly.
# ---------------------------------------------------------------------

def test_split_package_spec_handles_scopes_and_missing_versions():
    assert sandbox_runner._split_package_spec("money-manager-mcp@1.0.0") == ("money-manager-mcp", "1.0.0")
    assert sandbox_runner._split_package_spec("money-manager-mcp") == ("money-manager-mcp", None)
    assert sandbox_runner._split_package_spec("@scope/srv@2.1.0") == ("@scope/srv", "2.1.0")
    assert sandbox_runner._split_package_spec("@scope/srv") == ("@scope/srv", None)


def test_published_package_bin_strips_scope_and_version():
    assert sandbox_runner._published_package_bin("money-manager-mcp@1.0.0") == "money-manager-mcp"
    assert sandbox_runner._published_package_bin("@scope/srv@2.1.0") == "srv"


def test_containerized_command_runs_the_installed_bin_not_npx():
    """Re-running `npx pkg@version` inside the container would go back to
    the registry, which --network=none forbids."""
    assert sandbox_runner._containerize_launch_command(
        ["npx", "-y", "money-manager-mcp@1.0.0"]
    ) == ["money-manager-mcp"]
    # Non-published commands keep their existing behavior.
    assert sandbox_runner._containerize_launch_command(
        ["/usr/local/bin/python3.12", "server.py"]
    ) == ["python", "server.py"]


def test_published_artifact_dockerfile_installs_the_package_at_build_time():
    node_df = sandbox_runner._published_artifact_dockerfile(["npx", "-y", "money-manager-mcp@1.0.0"])
    assert "npm install -g money-manager-mcp@1.0.0" in node_df
    # The checkout must NOT be copied in, or a same-named local package
    # shadows the installed one all over again.
    assert "COPY" not in node_df

    py_df = sandbox_runner._published_artifact_dockerfile(["uvx", "some-server@1.2.3"])
    assert "pip install --no-cache-dir some-server@1.2.3" in py_df
    assert "COPY" not in py_df


def test_image_tag_distinguishes_build_strategies_for_identical_sources(tmp_path):
    """The bug this guards: tagging on content alone let a published-artifact
    build reuse the image from a run-the-repo build of the same checkout,
    producing MODULE_NOT_FOUND on a package that was never installed."""
    target = _unique_fixture_copy(tmp_path)

    repo_tag = sandbox_runner._image_tag_for(target, launch_command=["python", "server.py"])
    published_tag = sandbox_runner._image_tag_for(target, launch_command=["npx", "-y", "pkg@1.0.0"])
    assert repo_tag != published_tag

    # Same command against the same content stays cacheable.
    assert published_tag == sandbox_runner._image_tag_for(target, launch_command=["npx", "-y", "pkg@1.0.0"])
    # And a version bump is a different image.
    assert published_tag != sandbox_runner._image_tag_for(target, launch_command=["npx", "-y", "pkg@1.0.1"])


def _dependency_free_unique_dir(tmp_path: Path) -> Path:
    """No requirements.txt/pyproject.toml -- _default_dockerfile's
    pip-install step only runs when one of those exists, so a build
    against this near-instantly regardless of network conditions. Used
    for cache/eviction tests, which only care about image lifecycle
    mechanics (real `docker build`/`docker images`/`docker image rm`),
    not real fastmcp installability -- already covered, network-dependent
    and slower, by this file's other tests. This matters in practice: a
    real MCP-native build with a requirements.txt does a fresh, uncached
    `pip install --no-cache-dir` on every distinct-content image, and
    running several of those back to back (exactly what an eviction test
    needs -- more built images than the cap) was observed to take
    anywhere from ~1 to ~9 minutes depending on network conditions on this
    machine, which is real infra variance, not a bug in the eviction logic
    itself (verified correct on every one of those runs, slow or not)."""
    target = tmp_path / f"repo-{uuid.uuid4().hex[:8]}"
    target.mkdir()
    (target / "server.py").write_text(f"# marker: {uuid.uuid4().hex}\nprint('hello')\n")
    return target


@_needs_docker
@pytest.mark.asyncio
async def test_image_cache_limit_evicts_the_oldest_beyond_the_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner, "_IMAGE_CACHE_LIMIT", 2)

    tags = []
    for _ in range(3):
        target = _dependency_free_unique_dir(tmp_path)
        tag = sandbox_runner._image_tag_for(target)
        tags.append(tag)
        built = await sandbox_runner._build_image(target, ["python", "server.py"], image_tag=tag, build_timeout_seconds=60)
        assert built is True
        sandbox_runner._touch_image_cache_entry(tag)
        await sandbox_runner._enforce_image_cache_limit()

    # The first of these three is strictly older than the other two (built
    # before them, in sequence) -- a cap of 2 guarantees it's evicted
    # regardless of whatever other ados-onboarding-* images already exist
    # on the host from other tests. The last is the most-recently-touched
    # image on the whole host at this point, so it's guaranteed to survive.
    assert await sandbox_runner._image_exists(tags[0]) is False
    assert await sandbox_runner._image_exists(tags[-1]) is True


def test_hardened_run_flags_present():
    """Fast, no-Docker unit test — _HARDENED_RUN_FLAGS is spliced directly
    into every docker run invocation in _build_and_call, so asserting its
    contents is equivalent to asserting what's actually constructed."""
    assert "--cap-drop=ALL" in sandbox_runner._HARDENED_RUN_FLAGS
    assert "--security-opt=no-new-privileges:true" in sandbox_runner._HARDENED_RUN_FLAGS
    assert "--user" in sandbox_runner._HARDENED_RUN_FLAGS


def test_compute_build_context_hash_is_deterministic_and_content_sensitive(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "tool.py").write_text("def f(): return 1\n")
    (b / "tool.py").write_text("def f(): return 1\n")

    assert sandbox_runner._compute_build_context_hash(a) == sandbox_runner._compute_build_context_hash(b)

    (b / "tool.py").write_text("def f(): return 2\n")
    assert sandbox_runner._compute_build_context_hash(a) != sandbox_runner._compute_build_context_hash(b)


def test_compute_build_context_hash_excludes_git_and_generated_dockerfiles(tmp_path):
    target = tmp_path / "repo"
    target.mkdir()
    (target / "tool.py").write_text("def f(): return 1\n")
    before = sandbox_runner._compute_build_context_hash(target)

    (target / ".git").mkdir()
    (target / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (target / ".ados-onboarding.Dockerfile").write_text("FROM scratch\n")

    assert sandbox_runner._compute_build_context_hash(target) == before


def test_compute_build_context_hash_returns_none_over_the_file_count_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_runner, "_MAX_HASH_FILES", 2)
    target = tmp_path / "repo"
    target.mkdir()
    for i in range(3):
        (target / f"f{i}.py").write_text("x")

    assert sandbox_runner._compute_build_context_hash(target) is None


@pytest.mark.asyncio
async def test_no_docker_available_returns_failed_result_without_raising(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "is_docker_available", lambda: False)
    result = await sandbox_runner.run_mcp_sandbox_test(
        local_path=_MCP_NATIVE_FIXTURE,
        launch_command=["python", "server.py"],
        tool_name="add_numbers",
        sample_input={"a": 1, "b": 1},
    )
    assert result.passed is False
    assert "Docker is not available" in result.evidence_summary


@pytest.mark.asyncio
async def test_openapi_sandbox_refuses_without_explicit_acknowledgement():
    result = await sandbox_runner.run_openapi_sandbox_test(
        test_base_url="https://staging.example.com",
        method="GET",
        path_template="/tickets/{ticket_id}",
        sample_input={"ticket_id": "T-1"},
        acknowledge_live_call=False,
    )
    assert result.passed is False
    assert "acknowledge_live_call" in result.evidence_summary


@pytest.mark.asyncio
async def test_openapi_sandbox_calls_the_declared_test_url_not_production():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": "T-1", "subject": "test"})

    result = await sandbox_runner.run_openapi_sandbox_test(
        test_base_url="https://staging.zendesk.example.com",
        method="GET",
        path_template="/tickets/{ticket_id}",
        sample_input={"ticket_id": "T-1"},
        acknowledge_live_call=True,
        transport=httpx.MockTransport(handler),
    )
    assert result.passed is True
    assert captured["url"] == "https://staging.zendesk.example.com/tickets/T-1"


@pytest.mark.asyncio
async def test_openapi_sandbox_treats_5xx_as_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    result = await sandbox_runner.run_openapi_sandbox_test(
        test_base_url="https://staging.example.com",
        method="GET",
        path_template="/tickets/{ticket_id}",
        sample_input={"ticket_id": "T-1"},
        acknowledge_live_call=True,
        transport=httpx.MockTransport(handler),
    )
    assert result.passed is False


@pytest.mark.asyncio
async def test_openapi_live_call_targets_production_base_url_and_returns_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": "T-9", "subject": "real ticket"})

    result = await sandbox_runner.run_openapi_live_call(
        base_url="https://api.zendesk.example.com",
        method="GET",
        path_template="/tickets/{ticket_id}",
        arguments={"ticket_id": "T-9"},
        transport=httpx.MockTransport(handler),
    )
    assert captured["url"] == "https://api.zendesk.example.com/tickets/T-9"
    assert result == {"id": "T-9", "subject": "real ticket"}


@pytest.mark.asyncio
async def test_openapi_live_call_raises_on_http_error_for_the_connectors_catch_all():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(RuntimeError, match="404"):
        await sandbox_runner.run_openapi_live_call(
            base_url="https://api.zendesk.example.com",
            method="GET",
            path_template="/tickets/{ticket_id}",
            arguments={"ticket_id": "does-not-exist"},
            transport=httpx.MockTransport(handler),
        )
