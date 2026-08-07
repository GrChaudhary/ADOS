"""
orchestrate/onboarding/inspector.py — Turn 1 of the onboarding pipeline.
Runs against real fixtures under tests/fixtures/, not mocks: the MCP-native
fixture is a real FastMCP server actually launched over stdio by a real
fastmcp.Client (no network, no Docker — sandbox_runner.py is what adds
isolation, at Turn 4, after an admin has already reviewed what's found
here). The OpenAPI fixture is parsed directly, no external tooling needed
for this lightweight Turn-1 listing (full parameter-schema mapping happens
later, at synthesize() time, via openapi-mcp-generator-1).
"""

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from orchestrate.onboarding import inspector
from orchestrate.onboarding.models import OnboardingTrack


async def _async_return(value):
    """Lets a monkeypatched async function be written as a plain lambda."""
    return value

_FIXTURES = Path(__file__).parent / "fixtures"
_MCP_NATIVE_FIXTURE = _FIXTURES / "mcp_native_sample"
_OPENAPI_FIXTURE = _FIXTURES / "openapi_sample"
_UNCLASSIFIABLE_FIXTURE = _FIXTURES / "unclassifiable_sample"
_MCP_NATIVE_TS_FIXTURE = _FIXTURES / "mcp_native_typescript_sample"
_RAW_CODE_FIXTURE = _FIXTURES / "raw_code_sample"


def test_detect_track_infers_mcp_native_from_requirements_txt():
    track, confidence, smithery_config = inspector.detect_track(_MCP_NATIVE_FIXTURE)
    assert track is OnboardingTrack.MCP_NATIVE
    assert confidence == "inferred"
    assert smithery_config is None


def test_detect_track_finds_openapi_spec_with_high_confidence():
    track, confidence, _ = inspector.detect_track(_OPENAPI_FIXTURE)
    assert track is OnboardingTrack.OPENAPI
    assert confidence == "high"


def test_detect_track_returns_none_for_unclassifiable_source():
    track, confidence, _ = inspector.detect_track(_UNCLASSIFIABLE_FIXTURE)
    assert track is None
    assert confidence == "none"


@pytest.mark.asyncio
async def test_inspect_local_mcp_native_repo_discovers_real_tools():
    report = await inspector.inspect(str(_MCP_NATIVE_FIXTURE))

    assert report.track is OnboardingTrack.MCP_NATIVE
    assert report.confidence == "inferred"
    assert report.resolved_ref is None  # local path, nothing to resolve
    assert report.launch_command is not None and report.launch_command[-1].endswith("server.py")
    assert report.warnings == []

    tools_by_name = {t.name: t for t in report.tools}
    assert set(tools_by_name) == {"echo_message", "add_numbers", "send_welcome_back_message", "attempt_outbound_request"}
    assert tools_by_name["add_numbers"].description == "Add two integers and return the sum."
    assert tools_by_name["add_numbers"].input_schema["required"] == ["a", "b"]


@pytest.mark.asyncio
async def test_inspect_openapi_repo_lists_operations():
    report = await inspector.inspect(str(_OPENAPI_FIXTURE))

    assert report.track is OnboardingTrack.OPENAPI
    assert report.confidence == "high"
    assert report.openapi_spec_path is not None and report.openapi_spec_path.endswith("openapi.json")

    tools_by_name = {t.name: t for t in report.tools}
    assert set(tools_by_name) == {"read_ticket", "create_ticket"}
    assert tools_by_name["read_ticket"].description == "Fetch a support ticket by id"
    assert tools_by_name["read_ticket"].runtime == {"method": "GET", "path": "/tickets/{ticket_id}"}


@pytest.mark.asyncio
async def test_inspect_unclassifiable_repo_warns_instead_of_guessing():
    report = await inspector.inspect(str(_UNCLASSIFIABLE_FIXTURE))
    assert report.track is None
    assert report.tools == []
    assert any("couldn't classify" in w for w in report.warnings)


@pytest.mark.asyncio
async def test_inspect_rejects_a_nonexistent_local_path():
    with pytest.raises(ValueError, match="does not exist"):
        await inspector.inspect(str(_FIXTURES / "does-not-exist"))


@pytest.mark.asyncio
async def test_inspect_track_hint_overrides_detection_with_a_warning():
    report = await inspector.inspect(str(_OPENAPI_FIXTURE), track_hint="mcp_native")
    assert report.track is OnboardingTrack.MCP_NATIVE
    assert report.confidence == "hinted"
    assert any("conflicts with detected track" in w for w in report.warnings)


# ---------------------------------------------------------------------
# Workdir leak fixes (orchestrate/onboarding/cleanup.py's counterpart) —
# a local source must never mint an unused tempdir, and a failed remote
# clone must never leave an empty one behind either.
# ---------------------------------------------------------------------

def _onboarding_tempdirs() -> set:
    return {p.name for p in Path(tempfile.gettempdir()).glob("ados-onboarding-*")}


@pytest.mark.asyncio
async def test_inspect_local_source_never_creates_an_onboarding_tempdir():
    before = _onboarding_tempdirs()
    report = await inspector.inspect(str(_MCP_NATIVE_FIXTURE))
    after = _onboarding_tempdirs()

    assert after == before  # no new /tmp/ados-onboarding-* directory
    assert report.local_path == str(_MCP_NATIVE_FIXTURE.resolve())


@pytest.mark.asyncio
async def test_inspect_cleans_up_its_own_workdir_on_a_failed_remote_clone(monkeypatch):
    async def _boom(source, workdir):
        assert workdir.is_dir()  # inspect() must have created it before calling this
        raise RuntimeError("git clone failed for test-source: simulated network failure")

    monkeypatch.setattr(inspector, "_clone_or_fetch", _boom)

    before = _onboarding_tempdirs()
    with pytest.raises(RuntimeError, match="simulated network failure"):
        await inspector.inspect("https://example.invalid/does-not-matter.git")
    after = _onboarding_tempdirs()

    assert after == before  # the workdir created for this attempt is gone, not orphaned


@pytest.mark.asyncio
async def test_clone_or_fetch_normalizes_a_missing_git_binary_to_runtime_error(monkeypatch, tmp_path):
    """A real production concern: if the host running the backend doesn't
    have git on PATH, asyncio.create_subprocess_exec raises FileNotFoundError
    (a plain OSError subclass), not ValueError/RuntimeError — previously
    uncaught all the way up to an unhandled 500 on Turn 1."""
    async def _raise_file_not_found(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(inspector.asyncio, "create_subprocess_exec", _raise_file_not_found)

    with pytest.raises(RuntimeError, match="could not run git"):
        await inspector._clone_or_fetch("https://example.invalid/x.git", tmp_path)


@pytest.mark.asyncio
async def test_clone_or_fetch_times_out_instead_of_hanging_forever(monkeypatch, tmp_path):
    """git clone previously had no timeout at all — an unreachable or very
    slow remote host would hang the request indefinitely rather than
    failing cleanly."""
    class _NeverFinishes:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10_000)

        def kill(self):
            pass

        async def wait(self):
            return None

    async def _fake_exec(*args, **kwargs):
        return _NeverFinishes()

    monkeypatch.setattr(inspector.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(inspector, "_CLONE_TIMEOUT_SECONDS", 0.05)

    with pytest.raises(RuntimeError, match="timed out"):
        await inspector._clone_or_fetch("https://example.invalid/x.git", tmp_path)


def test_package_json_mentions_mcp_returns_false_instead_of_raising_when_unreadable(monkeypatch, tmp_path):
    """Matches _source_mentions_mcp_server's own "unreadable -> no signal"
    convention — this function was the one inconsistent spot that could
    raise OSError uncaught up through detect_track()/inspect()."""
    candidate = tmp_path / "package.json"
    candidate.write_text('{"name": "x"}')

    def _raise_oserror(self, *args, **kwargs):
        raise OSError("simulated unreadable file")

    monkeypatch.setattr(Path, "read_text", _raise_oserror)
    assert inspector._package_json_mentions_mcp(candidate) is False


@pytest.mark.asyncio
async def test_inspect_does_not_delete_a_caller_supplied_workdir_on_failure(tmp_path):
    """created_workdir is only True when inspect() minted the directory
    itself — a caller-supplied workdir (the multi-turn pipeline's own
    reuse case) must survive a failure exactly as before this fix."""
    async def _boom(source, workdir):
        raise RuntimeError("simulated failure")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(inspector, "_clone_or_fetch", _boom)
        with pytest.raises(RuntimeError):
            await inspector.inspect("https://example.invalid/does-not-matter.git", workdir=tmp_path)

    assert tmp_path.is_dir()


# ---------------------------------------------------------------------
# Real-world detection gap found onboarding github.com/spences10/
# mcp-sqlite-tools: a genuine MCP server using neither fastmcp nor
# @modelcontextprotocol/sdk (it uses `tmcp`), with a TypeScript-generic
# constructor call (`new McpServer<any>(`) the old plain-substring check
# didn't match. Fixed via a new, standardized signal (server.json, the
# official MCP registry manifest) plus a generics-tolerant source regex
# and broader package.json needles — tested independently below.
# ---------------------------------------------------------------------

def test_detect_track_finds_mcp_registry_manifest_with_high_confidence():
    track, confidence, smithery_config = inspector.detect_track(_MCP_NATIVE_TS_FIXTURE)
    assert track is OnboardingTrack.MCP_NATIVE
    assert confidence == "high"
    assert smithery_config is None  # no startCommand to reuse from server.json


def test_detect_track_falls_back_to_generics_tolerant_source_regex_without_a_manifest(tmp_path):
    target = tmp_path / "repo"
    shutil.copytree(_MCP_NATIVE_TS_FIXTURE, target)
    (target / "server.json").unlink()
    (target / "package.json").write_text('{"name": "no-mcp-markers-here"}')

    track, confidence, _ = inspector.detect_track(target)
    assert track is OnboardingTrack.MCP_NATIVE
    assert confidence == "inferred"


def test_detect_track_falls_back_to_broadened_package_json_needles_without_source_markers(tmp_path):
    target = tmp_path / "repo"
    shutil.copytree(_MCP_NATIVE_TS_FIXTURE, target)
    (target / "server.json").unlink()
    (target / "src" / "index.ts").write_text("export function nothingMcpRelated() {}\n")

    track, confidence, _ = inspector.detect_track(target)
    assert track is OnboardingTrack.MCP_NATIVE
    assert confidence == "inferred"


# ---------------------------------------------------------------------
# Launch-command derivation from server.json. Before this, detection
# correctly identified TypeScript/Node MCP servers as MCP_NATIVE but
# _find_fastmcp_entrypoint (Python-only) always came up empty, so every
# one of them landed on Turn 2 as "Discovered Tools (0)" plus a "couldn't
# determine a launch command" warning — detected but unusable.
# ---------------------------------------------------------------------

def test_launch_command_derives_npx_invocation_from_registry_manifest():
    manifest = inspector._find_mcp_registry_manifest(_MCP_NATIVE_TS_FIXTURE)
    command, warning = inspector._launch_command_from_registry_manifest(manifest)

    assert command == ["npx", "-y", "mcp-typescript-sample@0.0.1"]
    assert warning is None


def test_launch_command_pins_nothing_when_the_manifest_omits_a_version():
    manifest = {"packages": [{"registry_type": "npm", "identifier": "some-server"}]}
    command, warning = inspector._launch_command_from_registry_manifest(manifest)

    assert command == ["npx", "-y", "some-server"]
    assert warning is None


def test_launch_command_skips_non_stdio_transports():
    """An http/sse server needs a URL, not a subprocess — deriving a launch
    command for one would produce a process that can't be spoken to."""
    manifest = {"packages": [{
        "registry_type": "npm", "identifier": "remote-server",
        "transport": {"type": "sse"},
    }]}
    command, warning = inspector._launch_command_from_registry_manifest(manifest)

    assert command is None
    assert warning is None


def test_launch_command_reports_a_missing_runner_instead_of_guessing(monkeypatch):
    monkeypatch.setattr(inspector.shutil, "which", lambda _binary: None)
    manifest = inspector._find_mcp_registry_manifest(_MCP_NATIVE_TS_FIXTURE)
    command, warning = inspector._launch_command_from_registry_manifest(manifest)

    assert command is None
    assert "npx" in warning and "not installed" in warning


def test_launch_command_ignores_registries_with_no_fetch_and_run_runner():
    manifest = {"packages": [{"registry_type": "oci", "identifier": "ghcr.io/x/y"}]}
    command, warning = inspector._launch_command_from_registry_manifest(manifest)

    assert command is None
    assert warning is None


@pytest.mark.asyncio
async def test_inspect_derives_a_launch_command_for_a_typescript_server(monkeypatch):
    """The end-to-end gap: MCP_NATIVE + no Python entrypoint used to mean no
    launch command at all. Tool discovery itself is stubbed — the point is
    that inspect() now hands it something to run."""
    async def _fake_discover(local_path, launch_command):
        return []

    monkeypatch.setattr(inspector, "_discover_mcp_tools", _fake_discover)
    report = await inspector.inspect(source=str(_MCP_NATIVE_TS_FIXTURE))

    assert report.track is OnboardingTrack.MCP_NATIVE
    assert report.launch_command == ["npx", "-y", "mcp-typescript-sample@0.0.1"]
    assert not any("couldn't determine a launch command" in w for w in report.warnings)


# ---------------------------------------------------------------------
# npm-published servers that ship no server.json (real example:
# github.com/shahlaukik/money-manager-mcp). Detected as MCP_NATIVE, no
# Python entrypoint, no registry manifest -> previously zero tools.
# ---------------------------------------------------------------------

def _npm_package_json(tmp_path, **overrides) -> Path:
    target = tmp_path / "repo"
    target.mkdir(exist_ok=True)
    payload = {"name": "money-manager-mcp", "version": "1.0.0", "bin": {"money-manager-mcp": "dist/index.js"}}
    payload.update(overrides)
    (target / "package.json").write_text(json.dumps(payload))
    return target


@pytest.mark.asyncio
async def test_launch_command_uses_the_version_npm_actually_serves(tmp_path, monkeypatch):
    """Pins to the published version, not package.json's — repos routinely
    bump their version field ahead of what was ever released, and npx
    against an unpublished version fails confusingly."""
    async def _fake_published(name):
        assert name == "money-manager-mcp"
        return "1.0.0"

    monkeypatch.setattr(inspector, "_published_npm_version", _fake_published)
    command, warning = await inspector._launch_command_from_package_json(_npm_package_json(tmp_path))

    assert command == ["npx", "-y", "money-manager-mcp@1.0.0"]
    assert warning is None


@pytest.mark.asyncio
async def test_launch_command_warns_when_the_checkout_is_ahead_of_npm(tmp_path, monkeypatch):
    monkeypatch.setattr(inspector, "_published_npm_version", lambda _n: _async_return("1.0.0"))
    target = _npm_package_json(tmp_path, version="2.0.0-dev")
    command, warning = await inspector._launch_command_from_package_json(target)

    assert command == ["npx", "-y", "money-manager-mcp@1.0.0"]
    assert "2.0.0-dev" in warning and "not the repo HEAD" in warning


@pytest.mark.asyncio
async def test_unpublished_package_is_reported_rather_than_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(inspector, "_published_npm_version", lambda _n: _async_return(None))
    command, warning = await inspector._launch_command_from_package_json(_npm_package_json(tmp_path))

    assert command is None
    assert "not published to npm" in warning


@pytest.mark.asyncio
async def test_library_package_without_a_bin_is_not_launchable(tmp_path, monkeypatch):
    """No bin means it's a library, not a runnable server — deriving a
    command for it would just produce a failing npx call."""
    called = False

    async def _fake_published(_name):
        nonlocal called
        called = True
        return "1.0.0"

    monkeypatch.setattr(inspector, "_published_npm_version", _fake_published)
    target = tmp_path / "repo"
    target.mkdir()
    (target / "package.json").write_text('{"name": "some-lib", "version": "1.0.0"}')

    command, warning = await inspector._launch_command_from_package_json(target)
    assert command is None and warning is None
    assert called is False, "should not hit the registry for a package with no bin"


def test_runs_published_artifact_flags_package_runners():
    assert inspector.runs_published_artifact(["npx", "-y", "x@1"]) is True
    assert inspector.runs_published_artifact(["uvx", "x"]) is True
    assert inspector.runs_published_artifact(["/usr/local/bin/npx", "x"]) is True
    assert inspector.runs_published_artifact(["/usr/bin/python3", "server.py"]) is False
    assert inspector.runs_published_artifact(["node", "dist/index.js"]) is False
    assert inspector.runs_published_artifact([]) is False
    assert inspector.runs_published_artifact(None) is False


@pytest.mark.asyncio
async def test_published_artifact_is_discovered_outside_the_checkout(tmp_path, monkeypatch):
    """The subtle one: `npx foo` inside a clone whose package.json is also
    named "foo" runs the local (unbuilt) copy and dies with "command not
    found" instead of fetching from the registry."""
    target = _npm_package_json(tmp_path)
    monkeypatch.setattr(inspector, "_published_npm_version", lambda _n: _async_return("1.0.0"))

    seen = {}

    class _FakeTransport:
        def __init__(self, command, args, cwd):
            seen["cwd"] = cwd

    class _FakeClient:
        def __init__(self, transport): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def list_tools(self): return []

    import fastmcp
    import fastmcp.client.transports as transports
    monkeypatch.setattr(transports, "StdioTransport", _FakeTransport)
    monkeypatch.setattr(fastmcp, "Client", _FakeClient)

    await inspector._discover_mcp_tools(target, ["npx", "-y", "money-manager-mcp@1.0.0"])
    assert seen["cwd"] != str(target)

    await inspector._discover_mcp_tools(target, ["/usr/bin/python3", "server.py"])
    assert seen["cwd"] == str(target)


def test_package_json_mcp_detection_via_mcpname_field(tmp_path):
    candidate = tmp_path / "package.json"
    candidate.write_text('{"name": "x", "mcpName": "io.github.example/x"}')
    assert inspector._package_json_mentions_mcp(candidate) is True


def test_package_json_mcp_detection_via_keywords(tmp_path):
    candidate = tmp_path / "package.json"
    candidate.write_text('{"name": "x", "keywords": ["ai", "mcp"]}')
    assert inspector._package_json_mentions_mcp(candidate) is True


def test_package_json_no_mcp_signal_returns_false(tmp_path):
    candidate = tmp_path / "package.json"
    candidate.write_text('{"name": "x", "keywords": ["ai", "database"]}')
    assert inspector._package_json_mentions_mcp(candidate) is False


# ---------------------------------------------------------------------
# raw_code track — never auto-detected (no positive signal exists to
# infer it safely), only reachable via an explicit track_hint. Discovery
# is pure ast.parse — never imports/executes the target file.
# ---------------------------------------------------------------------

def test_detect_track_never_infers_raw_code_even_for_a_plain_python_module():
    track, confidence, _ = inspector.detect_track(_RAW_CODE_FIXTURE)
    assert track is None
    assert confidence == "none"


@pytest.mark.asyncio
async def test_inspect_raw_code_discovers_functions_via_ast():
    report = await inspector.inspect(str(_RAW_CODE_FIXTURE), track_hint="raw_code", entrypoint_path="tool.py")

    assert report.track is OnboardingTrack.RAW_CODE
    assert report.confidence == "hinted"
    assert report.raw_code_entrypoint == "tool.py"

    tools_by_name = {t.name: t for t in report.tools}
    assert set(tools_by_name) == {"add_numbers", "greet", "attempt_outbound_request"}  # _private_helper excluded

    add_numbers = tools_by_name["add_numbers"]
    assert add_numbers.description == "Add two integers and return the sum."
    assert add_numbers.input_schema == {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"],
    }
    assert add_numbers.runtime == {"entrypoint_path": "tool.py", "function_name": "add_numbers"}

    greet = tools_by_name["greet"]
    # `greeting` has a default -> not required, even though it's annotated
    assert greet.input_schema["required"] == ["name"]
    assert "greeting" in greet.input_schema["properties"]


@pytest.mark.asyncio
async def test_inspect_raw_code_requires_entrypoint_path():
    with pytest.raises(ValueError, match="entrypoint_path is required"):
        await inspector.inspect(str(_RAW_CODE_FIXTURE), track_hint="raw_code")


@pytest.mark.asyncio
async def test_inspect_raw_code_rejects_path_traversal():
    with pytest.raises(ValueError, match="escapes the repository root"):
        await inspector.inspect(str(_RAW_CODE_FIXTURE), track_hint="raw_code", entrypoint_path="../mcp_native_sample/server.py")


@pytest.mark.asyncio
async def test_inspect_raw_code_rejects_a_missing_entrypoint_file():
    with pytest.raises(ValueError, match="does not exist"):
        await inspector.inspect(str(_RAW_CODE_FIXTURE), track_hint="raw_code", entrypoint_path="does_not_exist.py")


@pytest.mark.asyncio
async def test_inspect_raw_code_rejects_a_syntax_error(tmp_path):
    (tmp_path / "broken.py").write_text("def f(:\n    pass\n")
    with pytest.raises(ValueError, match="could not parse"):
        await inspector.inspect(str(tmp_path), track_hint="raw_code", entrypoint_path="broken.py")


@pytest.mark.asyncio
async def test_inspect_raw_code_warns_when_no_eligible_functions(tmp_path):
    (tmp_path / "empty.py").write_text("def _only_private(): pass\n")
    report = await inspector.inspect(str(tmp_path), track_hint="raw_code", entrypoint_path="empty.py")
    assert report.tools == []
    assert any("no eligible top-level functions" in w for w in report.warnings)
