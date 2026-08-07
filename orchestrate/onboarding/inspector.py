"""
Turn 1 of the onboarding pipeline (orchestration-platform-vision.md §8.5) —
"paste a link, agent reflects back what it found... does not yet ask for
approval". Classifies a repo/local path into a track and, for MCP-native,
discovers its real tool list by actually running the server locally (not
sandboxed yet — see sandbox_runner.py for the isolated execution that
happens at Turn 4, after an admin has reviewed what was found here).

Detection is layered, most-reliable signal first:
  1. An OpenAPI/Swagger spec at a common path -> OPENAPI, high confidence.
  2. smithery.yaml at the repo root (the real filename per Smithery's own
     docs — not smithery.json) -> MCP_NATIVE, high confidence, and its
     startCommand is reused directly instead of inferred.
  3. server.json matching the official MCP registry manifest schema
     (https://static.modelcontextprotocol.io/schemas/2025-07-09/server.schema.json)
     -> MCP_NATIVE, high confidence — a standardized signal independent of
     implementation language/SDK, catches real servers (e.g. built on
     `tmcp` rather than fastmcp/@modelcontextprotocol/sdk) that the
     source/dependency heuristics below would otherwise miss.
  4. Fallback: fastmcp/@modelcontextprotocol/sdk (or an "mcp"-flavored
     `mcpName`/keywords entry) mentioned in a dependency manifest, or
     FastMCP(/@mcp.tool/McpServer(/new Server( found in source (tolerant
     of TS generics, e.g. `new McpServer<any>(`) -> MCP_NATIVE, "inferred"
     confidence, surfaced to the admin as unconfirmed rather than silently
     trusted.
Anything matching none of these returns track=None with a warning — v1
scope is MCP-native + OpenAPI only (see orchestrate/onboarding/__init__.py).
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from .models import DiscoveredTool, InspectionReport, OnboardingTrack

_OPENAPI_CANDIDATES = ["openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml"]
_FASTMCP_SOURCE_MARKERS = ("FastMCP(", "@mcp.tool")
# Plain substrings miss real-world TS servers written with generics, e.g.
# `new McpServer<any>(` (github.com/spences10/mcp-sqlite-tools, using the
# `tmcp` SDK) — the `<any>` sits between the class name and the paren.
_MCP_SDK_SOURCE_PATTERNS = (
    re.compile(r"McpServer\s*(?:<[^>]*>)?\s*\("),
    re.compile(r"new\s+Server\s*(?:<[^>]*>)?\s*\("),
)
_SOURCE_GLOB_PATTERNS = ("*.py", "*.ts", "*.js")
_MAX_SOURCE_FILES_SCANNED = 200


def _looks_like_remote(source: str) -> bool:
    return source.startswith(("http://", "https://", "git@", "ssh://"))


_CLONE_TIMEOUT_SECONDS = 60.0


async def _clone_or_fetch(source: str, workdir: Path) -> Tuple[Path, Optional[str]]:
    """Returns (local_path, resolved_git_sha). resolved_git_sha is None for
    a local path (nothing to resolve).

    Every failure mode here is normalized to ValueError/RuntimeError —
    the two exception types start_onboarding_session's caller already
    catches and turns into a clean 422 — rather than letting whatever a
    real `git` subprocess happens to raise (FileNotFoundError if git
    isn't on PATH, or an unbounded hang against an unreachable/slow host
    with no timeout at all, previously) escape as an unhandled 500.
    Inspecting an arbitrary admin-supplied external repo is exactly the
    boundary where "some exception type I didn't anticipate" should
    always degrade to a clean, retriable failure, never a crash."""
    if not _looks_like_remote(source):
        local_path = Path(source).expanduser().resolve()
        if not local_path.is_dir():
            raise ValueError(f"local_path does not exist or is not a directory: {local_path}")
        return local_path, None

    dest = workdir / "repo"
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--depth", "1", source, str(dest),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as e:
        raise RuntimeError(f"could not run git to clone {source}: {e}")

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=_CLONE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"git clone timed out after {_CLONE_TIMEOUT_SECONDS}s for {source} — host unreachable or too slow")
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed for {source}: {stderr.decode(errors='replace').strip()}")

    sha_proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(dest), "rev-parse", "HEAD",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    sha_out, _ = await sha_proc.communicate()
    resolved_ref = sha_out.decode().strip() if sha_proc.returncode == 0 else None
    return dest, resolved_ref


def _find_openapi_spec(local_path: Path) -> Optional[Path]:
    for candidate in _OPENAPI_CANDIDATES:
        for match in (local_path / candidate, *local_path.glob(f"**/{candidate}")):
            if match.is_file():
                return match
    return None


def _find_smithery_yaml(local_path: Path) -> Optional[Path]:
    candidate = local_path / "smithery.yaml"
    return candidate if candidate.is_file() else None


def _package_json_mentions_mcp(candidate: Path) -> bool:
    try:
        text = candidate.read_text(errors="replace")
    except OSError:
        # Matches _source_mentions_mcp_server/_find_fastmcp_entrypoint's own
        # "unreadable file -> treat as no signal, don't crash" convention —
        # this one was missing it, a real inconsistency: a package.json
        # that exists but can't be read (permissions, an unusual file mode
        # surviving a git clone) would otherwise raise OSError uncaught,
        # all the way up through detect_track()/inspect() into a 500.
        return False
    if "@modelcontextprotocol/sdk" in text or "fastmcp" in text.lower():
        return True
    # Not every legitimate MCP SDK is fastmcp/@modelcontextprotocol/sdk
    # (e.g. `tmcp`) — fall back to the package's own declared identity
    # instead of a raw whole-file substring scan (which would false-
    # positive on any package that merely mentions "mcp" in a URL or
    # description). `mcpName` and an "mcp" keyword are both part of the
    # real-world publishing convention for MCP servers on npm.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    if "mcpName" in data:
        return True
    keywords = data.get("keywords")
    return isinstance(keywords, list) and any(isinstance(k, str) and "mcp" in k.lower() for k in keywords)


def _dependency_manifests_mention_mcp(local_path: Path) -> bool:
    for filename, needles in (
        ("requirements.txt", ("fastmcp", "mcp")),
        ("pyproject.toml", ("fastmcp", "mcp")),
    ):
        candidate = local_path / filename
        if candidate.is_file() and any(needle in candidate.read_text(errors="replace").lower() for needle in needles):
            return True
    package_json = local_path / "package.json"
    return package_json.is_file() and _package_json_mentions_mcp(package_json)


def _find_mcp_registry_manifest(local_path: Path) -> Optional[dict]:
    """The official MCP registry server manifest (server.json, schema
    https://static.modelcontextprotocol.io/schemas/2025-07-09/server.schema.json)
    — a standardized, high-confidence signal any MCP server can ship
    regardless of implementation language/SDK. Real example that
    motivated this: github.com/spences10/mcp-sqlite-tools ships this but
    uses neither fastmcp nor @modelcontextprotocol/sdk."""
    candidate = local_path / "server.json"
    if not candidate.is_file():
        return None
    try:
        config = json.loads(candidate.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None
    return config if isinstance(config, dict) and "packages" in config else None


def _source_mentions_mcp_server(local_path: Path) -> bool:
    scanned = 0
    for pattern in _SOURCE_GLOB_PATTERNS:
        for path in local_path.glob(f"**/{pattern}"):
            if scanned >= _MAX_SOURCE_FILES_SCANNED:
                return False
            scanned += 1
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            if any(marker in text for marker in _FASTMCP_SOURCE_MARKERS):
                return True
            if any(p.search(text) for p in _MCP_SDK_SOURCE_PATTERNS):
                return True
    return False


def _find_fastmcp_entrypoint(local_path: Path) -> Optional[Path]:
    """Heuristic for the common FastMCP idiom: a script with
    `if __name__ == "__main__": mcp.run()`. Good enough for v1 — anything
    it can't find becomes a clear "couldn't determine a launch command"
    warning, not a silent guess."""
    scanned = 0
    for path in local_path.glob("**/*.py"):
        if scanned >= _MAX_SOURCE_FILES_SCANNED:
            break
        scanned += 1
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if "FastMCP(" in text and re.search(r"\.run\(\s*\)", text):
            return path
    return None


def detect_track(local_path: Path) -> Tuple[Optional[OnboardingTrack], str, Optional[dict]]:
    """Returns (track, confidence, smithery_config | None)."""
    if _find_openapi_spec(local_path) is not None:
        return OnboardingTrack.OPENAPI, "high", None

    smithery_path = _find_smithery_yaml(local_path)
    if smithery_path is not None:
        try:
            config = yaml.safe_load(smithery_path.read_text()) or {}
        except yaml.YAMLError:
            config = {}
        return OnboardingTrack.MCP_NATIVE, "high", config

    if _find_mcp_registry_manifest(local_path) is not None:
        # No startCommand to reuse here (unlike smithery.yaml) — launch
        # command derivation for non-Python raw manifests is out of scope
        # for v1; falls through to _find_fastmcp_entrypoint()'s Python-only
        # heuristic in inspect(), which honestly reports "needs manual
        # input" for a Node/TS target rather than guessing.
        return OnboardingTrack.MCP_NATIVE, "high", None

    if _dependency_manifests_mention_mcp(local_path) or _source_mentions_mcp_server(local_path):
        return OnboardingTrack.MCP_NATIVE, "inferred", None

    return None, "none", None


# registry_type -> (runner binary, argv builder). Only registries whose
# runner can fetch-and-execute a published server in one shot.
_REGISTRY_RUNNERS = {
    "npm": ("npx", lambda spec: ["npx", "-y", spec]),
    "pypi": ("uvx", lambda spec: ["uvx", spec]),
}


def _launch_command_from_registry_manifest(manifest: dict) -> Tuple[Optional[List[str]], Optional[str]]:
    """Derives a launch command from server.json's `packages[]`.

    Launches the *published artifact* (npx/uvx) rather than the clone,
    because a checkout usually has nothing runnable in it: the build output
    is gitignored (mcp-sqlite-tools, the repo this manifest support was
    written for, ships dist/ to npm only), so `node dist/index.js` against
    a fresh clone would just ENOENT. This is what finally makes non-Python
    MCP servers discoverable — _find_fastmcp_entrypoint below is Python-only,
    so before this every Node/TS server fell through to "needs manual input"
    with zero tools.

    Returns (launch_command, warning); either may be None.
    """
    for package in (manifest or {}).get("packages") or []:
        if not isinstance(package, dict):
            continue
        # Only stdio servers can be spawned as a subprocess and spoken to
        # over pipes; http/sse ones would need a URL, not a command.
        transport_type = ((package.get("transport") or {}).get("type") or "stdio").lower()
        if transport_type != "stdio":
            continue
        identifier = package.get("identifier")
        registry = (package.get("registry_type") or "").lower()
        if not identifier or registry not in _REGISTRY_RUNNERS:
            continue
        runner, build_argv = _REGISTRY_RUNNERS[registry]
        if shutil.which(runner) is None:
            return None, (
                f"server.json publishes this server to {registry}, but {runner!r} is not "
                f"installed — install it or supply a launch command manually"
            )
        version = package.get("version")
        return build_argv(f"{identifier}@{version}" if version else identifier), None
    return None, None


_NPM_VIEW_TIMEOUT_SECONDS = 30.0

# Runners that fetch a published package and execute it. Both resolve a
# same-named package from the current directory ahead of the registry, which
# matters wherever these commands get run — see runs_published_artifact.
_PACKAGE_RUNNERS = frozenset({"npx", "uvx"})


def runs_published_artifact(launch_command: Optional[List[str]]) -> bool:
    """True when the launch command fetches a published package rather than
    executing the checkout.

    Callers must NOT run these from inside the cloned repo: `npx foo` in a
    directory whose package.json is also named "foo" resolves to that local
    package and tries to run its (gitignored, absent) build output, failing
    with `sh: foo: command not found` instead of fetching from npm.
    """
    if not launch_command:
        return False
    return Path(launch_command[0]).name in _PACKAGE_RUNNERS


async def _published_npm_version(package_name: str) -> Optional[str]:
    """The version npm actually serves for `package_name`, or None.

    Asking the registry rather than trusting package.json's own version:
    a repo's version field is routinely bumped ahead of (or independently
    of) what is published, and pinning npx to a version that was never
    released fails with a confusing npm error at tool-discovery time.
    """
    if shutil.which("npm") is None:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "view", package_name, "version",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError:
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_NPM_VIEW_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    version = stdout.decode(errors="replace").strip()
    return version or None


async def _launch_command_from_package_json(local_path: Path) -> Tuple[Optional[List[str]], Optional[str]]:
    """Derives `npx -y <name>@<version>` for an npm-published MCP server that
    ships no server.json.

    Gated on a `bin` entry (the package declares itself runnable as a CLI,
    rather than being a library) *and* the registry confirming the name is
    really published. Guessing an unpublished name would hand tool discovery
    a command that dies with an opaque npm error instead of the honest
    "needs manual input" warning.

    Returns (launch_command, warning); either may be None.
    """
    candidate = local_path / "package.json"
    if not candidate.is_file():
        return None, None
    try:
        config = json.loads(candidate.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None, None
    if not isinstance(config, dict) or not config.get("bin"):
        return None, None

    name = config.get("name")
    if not isinstance(name, str) or not name:
        return None, None

    published = await _published_npm_version(name)
    if published is None:
        return None, (
            f"package.json declares a runnable bin but {name!r} is not published to npm — "
            "supply a launch command manually"
        )

    warning = None
    local_version = config.get("version")
    if isinstance(local_version, str) and local_version and local_version != published:
        # Onboarding the published artifact, which is not what this checkout
        # contains. Governance decisions get made against the tools listed
        # below, so say plainly which build they came from.
        warning = (
            f"inspected npm-published {name}@{published}, but this checkout is version "
            f"{local_version} — discovered tools reflect the published build, not the repo HEAD"
        )
    return ["npx", "-y", f"{name}@{published}"], warning


def _launch_command_from_smithery(config: dict, local_path: Path) -> Optional[List[str]]:
    start_command = (config or {}).get("startCommand") or {}
    command = start_command.get("command")
    if not command:
        return None
    args = start_command.get("args") or []
    return [command, *args]


async def _discover_mcp_tools(local_path: Path, launch_command: List[str]) -> List[DiscoveredTool]:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    # A published-artifact command must not run inside the checkout, or the
    # clone's own package.json shadows the registry package.
    cwd = tempfile.gettempdir() if runs_published_artifact(launch_command) else str(local_path)
    transport = StdioTransport(command=launch_command[0], args=launch_command[1:], cwd=cwd)
    async with Client(transport) as client:
        tools = await client.list_tools()
    return [
        DiscoveredTool(
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.inputSchema or {},
            runtime={"launch_command": launch_command},
        )
        for tool in tools
    ]


def _discover_openapi_operations(spec_path: Path) -> List[DiscoveredTool]:
    """Lightweight direct parse — lists operations for Turn 1 display.
    Full parameter-schema mapping happens at synthesize() time via
    wrapper_generator.synthesize_openapi_action (openapi-mcp-generator-1),
    not here — this only needs to be good enough to pick from."""
    text = spec_path.read_text()
    spec = json.loads(text) if spec_path.suffix == ".json" else yaml.safe_load(text)
    tools: List[DiscoveredTool] = []
    for path, methods in (spec.get("paths") or {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete") or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId") or f"{method.lower()}_{path}"
            description = operation.get("summary") or operation.get("description") or ""
            tools.append(
                DiscoveredTool(
                    name=operation_id,
                    description=description,
                    input_schema={},
                    runtime={"method": method.upper(), "path": path},
                )
            )
    return tools


_MAX_RAW_CODE_ENTRYPOINT_BYTES = 2_000_000
_AST_TYPE_TO_JSON_SCHEMA = {"int": "integer", "str": "string", "float": "number", "bool": "boolean", "list": "array", "dict": "object"}


def _json_schema_type_for_annotation(annotation: Optional[ast.expr]) -> Optional[str]:
    if isinstance(annotation, ast.Name):
        return _AST_TYPE_TO_JSON_SCHEMA.get(annotation.id)
    return None


def _input_schema_from_args(args: ast.arguments) -> dict:
    """Best-effort JSON-Schema-ish mapping from a function's type-hinted
    parameters — a Turn-1 selection aid, not a strict validator.
    Unannotated parameters still get a (typeless) schema entry rather than
    being dropped, so the admin sees every real parameter name. *args/
    **kwargs and keyword-only params are intentionally not represented —
    raw_code targets an ordinary, fully positional-or-keyword signature."""
    properties: dict = {}
    required: List[str] = []
    defaulted = set(a.arg for a in args.args[len(args.args) - len(args.defaults):]) if args.defaults else set()
    for arg in args.args:
        if arg.arg == "self":
            continue
        json_type = _json_schema_type_for_annotation(arg.annotation)
        properties[arg.arg] = {"type": json_type} if json_type else {}
        if arg.arg not in defaulted:
            required.append(arg.arg)
    schema: dict = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _discover_raw_code_functions(local_path: Path, entrypoint_path: str) -> List[DiscoveredTool]:
    """AST-only static analysis — never imports/executes the target file
    (that only ever happens later, sandboxed, via
    vendor/raw_code_runner.py). A Turn-1 selection aid, not a security
    control on its own, but defended in depth anyway: entrypoint_path is a
    new, free-text, admin-supplied field with no precedent elsewhere in
    this pipeline (the other two tracks always discover their own
    entrypoint by globbing *inside* local_path, never taking an external
    path), so this runs unsandboxed on the ADOS host exactly like the
    other tracks' Turn-1 discovery — path traversal and a read-size cap
    are enforced before anything touches the file."""
    root = local_path.resolve()
    resolved = (local_path / entrypoint_path).resolve()
    if root not in resolved.parents:
        raise ValueError(f"entrypoint_path {entrypoint_path!r} escapes the repository root")
    if not resolved.is_file():
        raise ValueError(f"entrypoint_path {entrypoint_path!r} does not exist in this repository")
    if resolved.stat().st_size > _MAX_RAW_CODE_ENTRYPOINT_BYTES:
        raise ValueError(f"entrypoint_path {entrypoint_path!r} exceeds the {_MAX_RAW_CODE_ENTRYPOINT_BYTES}-byte inspection limit")

    try:
        tree = ast.parse(resolved.read_text(errors="replace"), filename=str(resolved))
    except SyntaxError as e:
        raise ValueError(f"could not parse {entrypoint_path!r} as Python: {e}")

    tools: List[DiscoveredTool] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
            continue
        doc = (ast.get_docstring(node) or "").strip()
        tools.append(
            DiscoveredTool(
                name=node.name,
                description=doc.splitlines()[0] if doc else node.name,
                input_schema=_input_schema_from_args(node.args),
                runtime={"entrypoint_path": entrypoint_path, "function_name": node.name},
            )
        )
    return tools


async def inspect(
    source: str, *, track_hint: Optional[str] = None, entrypoint_path: Optional[str] = None, workdir: Optional[Path] = None
) -> InspectionReport:
    """workdir, when given a remote source, is where the repo gets cloned
    to. Deliberately NOT auto-cleaned up here on a *successful* clone even
    when omitted (a fresh persistent directory is created instead of a
    self-deleting TemporaryDirectory) — this is a conversational,
    multi-turn pipeline; synthesize()/sandbox_runner() need the same clone
    still on disk in a later turn, potentially a separate process/request
    entirely. The caller (orchestrate/onboarding/cleanup.py, wired into
    the onboarding session's own lifecycle) owns cleanup once a session's
    workdir is no longer needed or has gone stale.

    Only ever created lazily, for a remote source specifically — a local
    `source` path is returned unchanged by _clone_or_fetch and never
    touches workdir at all, so unconditionally mkdtemp'ing one here (the
    original v1 behavior) silently leaked one empty, permanently-orphaned
    directory per LOCAL inspection too, not just failed remote clones.
    On a clone failure, a workdir this call created itself is immediately
    removed before re-raising — nothing was ever successfully cloned into
    it, so there's nothing later worth preserving it for."""
    import tempfile

    warnings: List[str] = []
    created_workdir = workdir is None and _looks_like_remote(source)
    if created_workdir:
        workdir = Path(tempfile.mkdtemp(prefix="ados-onboarding-"))

    try:
        local_path, resolved_ref = await _clone_or_fetch(source, workdir)
    except Exception:
        if created_workdir:
            shutil.rmtree(workdir, ignore_errors=True)
        raise
    track, confidence, smithery_config = detect_track(local_path)

    if track_hint is not None:
        hinted = OnboardingTrack(track_hint)
        if track is not None and hinted != track:
            warnings.append(
                f"track_hint={track_hint!r} conflicts with detected track {track.value!r} — using the hint"
            )
        track, confidence = hinted, "hinted"

    report = InspectionReport(
        source=source,
        track=track,
        confidence=confidence,
        local_path=str(local_path),
        resolved_ref=resolved_ref,
        warnings=warnings,
    )

    if track is OnboardingTrack.MCP_NATIVE:
        launch_command = (
            _launch_command_from_smithery(smithery_config, local_path) if smithery_config else None
        )
        if launch_command is None:
            entrypoint = _find_fastmcp_entrypoint(local_path)
            if entrypoint is not None:
                launch_command = [sys.executable, str(entrypoint.relative_to(local_path))]
        if launch_command is None:
            # Last resort: run the published artifact named in server.json.
            # Ordered after the source-based heuristics above so a repo we
            # can run directly is still run directly.
            registry_manifest = _find_mcp_registry_manifest(local_path)
            if registry_manifest is not None:
                launch_command, registry_warning = _launch_command_from_registry_manifest(registry_manifest)
                if registry_warning:
                    report.warnings.append(registry_warning)
        if launch_command is None:
            # Node/TS servers that ship no server.json but are on npm.
            launch_command, npm_warning = await _launch_command_from_package_json(local_path)
            if npm_warning:
                report.warnings.append(npm_warning)
        report.launch_command = launch_command
        if launch_command is None:
            report.warnings.append("detected MCP-native but couldn't determine a launch command — needs manual input")
        else:
            try:
                report.tools = await _discover_mcp_tools(local_path, launch_command)
            except Exception as e:  # noqa: BLE001 — surfaced to the admin, not a crash
                report.warnings.append(f"tool discovery failed: {type(e).__name__}: {e}")

    elif track is OnboardingTrack.OPENAPI:
        spec_path = _find_openapi_spec(local_path)
        report.openapi_spec_path = str(spec_path) if spec_path else None
        if spec_path is not None:
            try:
                report.tools = _discover_openapi_operations(spec_path)
            except Exception as e:  # noqa: BLE001
                report.warnings.append(f"OpenAPI spec parsing failed: {type(e).__name__}: {e}")

    elif track is OnboardingTrack.RAW_CODE:
        if not entrypoint_path:
            raise ValueError("entrypoint_path is required for the raw_code track")
        report.raw_code_entrypoint = entrypoint_path
        report.tools = _discover_raw_code_functions(local_path, entrypoint_path)
        if not report.tools:
            report.warnings.append(
                f"no eligible top-level functions found in {entrypoint_path!r} — every function is either "
                "underscore-prefixed or none are defined at module level"
            )

    else:
        report.warnings.append(
            "couldn't classify this source as MCP-native or OpenAPI — raw-code onboarding requires an explicit track_hint"
        )

    return report
