"""
Turn 4 of the onboarding pipeline (§8.4 step 4) — "sandbox testing is
always mandatory, with no fast-forward or skip option". This is the one
step in the whole pipeline that produces real execution evidence rather
than inference/proposal (§8.4's own framing) — no capability reaches
CapabilityManifestRegistry.record_sandbox_evidence() without actually
running here first.

MCP-native track: two-phase, deliberately not a bare read-only code mount
— a network-isolated container can't `pip install`/`npm install` at run
time. Phase 1 (_build_image) uses the target repo's own Dockerfile if
present, else a minimal one generated here; that build step gets network
access, since it isn't the untrusted-execution step. Phase 2 is a fresh,
throwaway CONTAINER with --network=none, memory/cpu/pid limits, a
read-only root filesystem (a small tmpfs for /tmp only), and --cap-drop
ALL/no-new-privileges/non-root — spawned directly as fastmcp.Client's
stdio transport, wrapped in a hard timeout. Note the timeout kills the
local `docker run` client process, not the container itself (they're
decoupled — containers are supervised by dockerd/containerd), so cleanup
also issues an explicit `docker kill` on the container's own name.

The built IMAGE is content-hash-tagged and deliberately NOT deleted after
use — it persists and is reused by later calls against the same unchanged
source (bounded by a small cache-eviction pass), so a live call against an
already-activated capability doesn't rebuild from scratch every time. This
is a real change from a "fresh image every call" first pass: the container
is still fresh and stateless on every single call regardless of caching —
only the (read-only, pre-tested) image layer is ever reused.

v1 supports STDIO-transport MCP servers only, matching
inspector.py/wrapper_generator.py's launch_command shape.

OpenAPI track: no Docker isolation is possible — the capability's entire
point is reaching a real external API, so there is nothing to sandbox in
the code-execution sense. See run_openapi_sandbox_test.

Every failure mode here — Docker unavailable, build failure, timeout, a
failed tool call — returns a SandboxResult(passed=False, ...) rather than
raising, matching this codebase's established connector convention
(ServiceNowConnector/SAPConnector: a degraded environment produces a clean
FAILED-shaped result, not an exception the caller has to guess how to
handle) — sandbox evidence is exactly as valuable when it records a real
failure as when it records a real pass.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import inspector

_PYTHON_INTERPRETER_PATTERN = re.compile(r"^python3?(\.\d+)?$")
_NODE_LIKE_COMMANDS = {"node", "npx", "npm"}

# --- Image content-hash caching + isolation hardening -----------------
_MAX_HASH_FILES = 500
_MAX_HASH_BYTES = 25_000_000
_HASH_EXCLUDED_NAMES = {
    ".git", "__pycache__", ".pytest_cache",
    ".ados-onboarding.Dockerfile", ".ados-raw-code.Dockerfile", ".ados-raw-code-runner.py",
}
_IMAGE_CACHE_LIMIT = int(os.environ.get("ADOS_ONBOARDING_IMAGE_CACHE_LIMIT", "20"))
_IMAGE_CACHE_STATE_PATH = Path(
    os.environ.get("ADOS_ONBOARDING_CACHE_STATE_DIR", tempfile.gettempdir())
) / "ados-onboarding-image-cache.json"
# MCP stdio servers / OpenAPI shims never need root or Linux capabilities
# — applied unconditionally to every track's call phase, not just
# raw_code's (raw_code is the highest-risk track, but there's no reason
# the existing tracks should run with a weaker posture than necessary).
_HARDENED_RUN_FLAGS = [
    "--cap-drop=ALL",
    "--security-opt=no-new-privileges:true",
    "--user", "65534:65534",  # nobody:nogroup — present by default on the
                               # python:*-slim / node:*-slim base images used here
]


@dataclass
class SandboxResult:
    passed: bool
    evidence_summary: str
    raw_output: str
    duration_ms: int


def is_docker_available() -> bool:
    return shutil.which("docker") is not None


def _containerize_launch_command(launch_command: List[str]) -> List[str]:
    """launch_command from inspector.py may carry a host-specific
    interpreter path (sys.executable — correct for local Turn-1 discovery
    on the ADOS host, meaningless inside a fresh container). Swap it for
    the generic command name the container image itself provides."""
    if inspector.runs_published_artifact(launch_command):
        # The package is installed into the image at build time, so run its
        # bin directly. Re-running `npx pkg@version` here would go back to
        # the registry, which --network=none forbids.
        return [_published_package_bin(launch_command[-1])]
    head, *rest = launch_command
    name = Path(head).name
    if _PYTHON_INTERPRETER_PATTERN.match(name):
        return ["python", *rest]
    return [name, *rest]


def _split_package_spec(spec: str) -> Tuple[str, Optional[str]]:
    """Splits "name@version" into its parts, tolerating npm scopes
    ("@scope/name@1.2.3" -> ("@scope/name", "1.2.3"))."""
    if spec.startswith("@"):
        at = spec.rfind("@")
        return (spec[:at], spec[at + 1:]) if at > 0 else (spec, None)
    name, _, version = spec.partition("@")
    return name, (version or None)


def _published_package_bin(spec: str) -> str:
    """The executable a published package puts on PATH once installed.

    Convention (holds for the MCP servers seen so far): the bin is named
    after the package, minus any npm scope. If a package breaks that, the
    container fails with a plain "command not found" rather than anything
    silent.
    """
    name, _version = _split_package_spec(spec)
    return name.split("/")[-1]


def _published_artifact_dockerfile(launch_command: List[str]) -> str:
    """Image for a launch command that fetches a published package.

    The package is installed at BUILD time (which has network) so the
    sandbox itself can stay on --network=none: `npx pkg@version` resolves
    the version against the registry on every run, which is exactly what an
    isolated container cannot do (it fails EAI_AGAIN). The checkout is
    deliberately NOT copied in — we are running the published artifact, not
    the repo, and copying it back would re-create the shadowing problem
    where a same-named local package wins over the installed one.
    """
    runner, spec = launch_command[0], launch_command[-1]
    if Path(runner).name == "uvx":
        return (
            "FROM python:3.12-slim\n"
            f"RUN pip install --no-cache-dir {spec}\n"
            "ENV HOME=/tmp\n"
        )
    return (
        "FROM node:22-slim\n"
        f"RUN npm install -g {spec}\n"
        # The container runs read-only as nobody; give the server a writable
        # HOME so anything touching a cache/config dir doesn't die on
        # /nonexistent.
        "ENV HOME=/tmp\n"
    )


def _default_dockerfile(runtime_command: str) -> str:
    if runtime_command in _NODE_LIKE_COMMANDS:
        return (
            "FROM node:22-slim\n"
            "WORKDIR /workspace\n"
            "COPY . /workspace\n"
            "RUN if [ -f package.json ]; then (npm ci --omit=dev || npm install --omit=dev); fi\n"
        )
    return (
        "FROM python:3.12-slim\n"
        "WORKDIR /workspace\n"
        "COPY . /workspace\n"
        "RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; "
        "elif [ -f pyproject.toml ]; then pip install --no-cache-dir .; fi\n"
    )


async def _run_subprocess(*args: str, timeout_seconds: float) -> Tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"command timed out after {timeout_seconds}s: {' '.join(args)}")
    return proc.returncode, stdout.decode(errors="replace")


def _compute_build_context_hash(local_path: Path) -> Optional[str]:
    """Deterministic content hash of the build context, used as the Docker
    image tag so repeat calls against unchanged source reuse the same
    image instead of rebuilding from scratch. Full content hash (not
    git-SHA-based — a locally-supplied local_path may not be a git repo at
    all, and nothing guards against out-of-band drift at a captured SHA;
    not mtime-based — mtimes aren't reliable across re-clones), length-
    prefixed per field to avoid ambiguous concatenation (("ab","c") vs
    ("a","bc")).

    Returns None if the scan exceeds _MAX_HASH_FILES/_MAX_HASH_BYTES —
    callers MUST treat that as an unconditional cache-miss (fall back to a
    fresh UUID tag), never as a reason to hash a truncated subset. A false
    cache MISS just costs an extra rebuild; a false cache HIT would serve
    stale/wrong code, which is the actually dangerous direction."""
    hasher = hashlib.sha256()
    total_bytes = 0
    paths = sorted(
        p for p in local_path.rglob("*")
        if p.is_file() and not any(part in _HASH_EXCLUDED_NAMES for part in p.relative_to(local_path).parts)
    )
    if len(paths) > _MAX_HASH_FILES:
        return None
    for path in paths:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        total_bytes += len(data)
        if total_bytes > _MAX_HASH_BYTES:
            return None
        rel = str(path.relative_to(local_path)).encode()
        hasher.update(len(rel).to_bytes(4, "big"))
        hasher.update(rel)
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
    return hasher.hexdigest()[:16]


def _image_tag_for(
    local_path: Path, *, prefix: str = "ados-onboarding", launch_command: Optional[List[str]] = None
) -> str:
    """Content-derived image tag.

    The launch command is part of the key, not just the source content: the
    same checkout can be built two completely different ways (run the repo
    vs. install a published package, see _build_image), and keying on
    content alone made the second one silently reuse the first one's image
    — the container then fails MODULE_NOT_FOUND on a package that was never
    installed. Cache keys have to cover everything that changes the image.
    """
    content_hash = _compute_build_context_hash(local_path)
    if content_hash is None:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"
    if launch_command:
        digest = hashlib.sha256(content_hash.encode())
        for part in launch_command:
            digest.update(f"{len(part)}:{part}".encode())
        content_hash = digest.hexdigest()[:32]
    return f"{prefix}-{content_hash}"


async def _image_exists(image_tag: str) -> bool:
    returncode, output = await _run_subprocess("docker", "images", "-q", image_tag, timeout_seconds=15.0)
    return returncode == 0 and output.strip() != ""


def _load_image_cache_state() -> Dict[str, str]:
    try:
        return json.loads(_IMAGE_CACHE_STATE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _touch_image_cache_entry(image_tag: str) -> None:
    """Best-effort local recency bookkeeping (touched on every call, hit or
    miss — a local file read/write, no subprocess) so
    _enforce_image_cache_limit can approximate real LRU eviction rather
    than pure build-order FIFO. Never raises — losing this bookkeeping
    only degrades eviction quality, it must never break a real onboarding
    call."""
    try:
        state = _load_image_cache_state()
        state[image_tag] = datetime.now(timezone.utc).isoformat()
        _IMAGE_CACHE_STATE_PATH.write_text(json.dumps(state))
    except OSError:
        pass


async def _enforce_image_cache_limit(limit: Optional[int] = None) -> None:
    """Bounds the onboarding image cache's on-disk growth now that images
    persist across calls instead of being deleted after every one (see
    _build_and_call). Only ever called after a build that actually
    happened, never on a cache hit, so it adds no subprocess overhead to
    the fast (already-cached) path. Eviction order: the local recency
    sidecar when available (real LRU), falling back to `docker images`'
    own CreatedAt for any tag it doesn't know about (e.g. an image built
    before this bookkeeping existed) — an honestly-approximate v1, not a
    perfected implementation.

    `limit` defaults to None (resolved against the module-level
    _IMAGE_CACHE_LIMIT at CALL time, not def time) rather than being bound
    as `limit: int = _IMAGE_CACHE_LIMIT` directly — a plain default
    argument is evaluated once at import, so tests (or any caller)
    patching _IMAGE_CACHE_LIMIT afterward would silently have no effect
    on calls that rely on the default."""
    effective_limit = _IMAGE_CACHE_LIMIT if limit is None else limit
    returncode, output = await _run_subprocess(
        "docker", "images", "--filter", "reference=ados-onboarding-*",
        "--format", "{{.Repository}} {{.CreatedAt}}", timeout_seconds=15.0,
    )
    if returncode != 0:
        return
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) <= effective_limit:
        return

    state = _load_image_cache_state()

    def _sort_key(line: str) -> str:
        tag, _, created_at = line.partition(" ")
        return state.get(tag) or created_at

    lines.sort(key=_sort_key)
    for line in lines[: len(lines) - effective_limit]:
        tag = line.split(" ", 1)[0]
        await _run_subprocess("docker", "image", "rm", "-f", tag, timeout_seconds=30.0)
        state.pop(tag, None)
    try:
        _IMAGE_CACHE_STATE_PATH.write_text(json.dumps(state))
    except OSError:
        pass


async def _build_image(local_path: Path, launch_command: List[str], *, image_tag: str, build_timeout_seconds: float) -> bool:
    """Returns True if a build subprocess actually ran, False on a cache
    hit (an image already exists under this content-derived tag) — exposed
    so callers/tests can assert on real cache behavior directly rather
    than inferring it from subprocess call counts or wall-clock time."""
    if await _image_exists(image_tag):
        return False

    dockerfile_path = local_path / "Dockerfile"
    generated_dockerfile: Optional[Path] = None
    published = inspector.runs_published_artifact(launch_command)
    # A published-artifact run ignores any Dockerfile the repo ships: that
    # one builds the checkout, which is not what gets executed here, and it
    # would leave the package itself uninstalled.
    if published or not dockerfile_path.is_file():
        generated_dockerfile = local_path / ".ados-onboarding.Dockerfile"
        if published:
            generated_dockerfile.write_text(_published_artifact_dockerfile(launch_command))
        else:
            runtime_command = _containerize_launch_command(launch_command)[0]
            generated_dockerfile.write_text(_default_dockerfile(runtime_command))
        dockerfile_path = generated_dockerfile

    try:
        returncode, output = await _run_subprocess(
            "docker", "build", "-f", str(dockerfile_path), "-t", image_tag, str(local_path),
            timeout_seconds=build_timeout_seconds,
        )
        if returncode != 0:
            raise RuntimeError(f"docker build failed (exit {returncode}):\n{output[-4000:]}")
    finally:
        if generated_dockerfile is not None:
            generated_dockerfile.unlink(missing_ok=True)
    return True


async def _build_and_call(
    *,
    local_path: str,
    launch_command: List[str],
    tool_name: str,
    arguments: Dict[str, Any],
    allow_network: bool,
    timeout_seconds: float,
    build_timeout_seconds: float,
    memory_limit: str,
    cpus: str,
    pids_limit: int,
) -> Tuple[Any, int]:
    """Shared core for both the sandbox test (allow_network=False, one
    specific verification call) and live post-activation invocation
    (allow_network=True — a live capability's whole point is usually
    reaching the real external system it was onboarded for, so locking out
    network here the same way the sandbox test does would just break every
    real capability). The IMAGE is content-hash-tagged and cached/reused
    across calls (see _image_tag_for/_build_image) — only a cache miss
    triggers a real `docker build`. The CONTAINER is still fresh and
    stateless on every single call regardless (--rm, unconditional).
    Raises on any failure — callers decide how to shape that (see
    run_mcp_sandbox_test's try/except vs. run_mcp_live_call's raise-through)."""
    path = Path(local_path)
    image_tag = _image_tag_for(path, launch_command=launch_command)
    built = await _build_image(path, launch_command, image_tag=image_tag, build_timeout_seconds=build_timeout_seconds)
    _touch_image_cache_entry(image_tag)
    if built:
        await _enforce_image_cache_limit()

    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    container_name = f"ados-onboarding-run-{uuid.uuid4().hex[:12]}"
    docker_run_args = [
        "run", "-i", "--rm", f"--name={container_name}",
        f"--memory={memory_limit}",
        f"--memory-swap={memory_limit}",  # pins swap accounting to the memory limit -- unset, Docker allows up to 2x via swap
        f"--cpus={cpus}",
        f"--pids-limit={pids_limit}",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        *_HARDENED_RUN_FLAGS,
    ]
    if not allow_network:
        docker_run_args.append("--network=none")
    if inspector.runs_published_artifact(launch_command):
        # The image still has the checkout at /workspace, but npx/uvx would
        # resolve the same-named local package from there instead of the
        # registry. /tmp is the writable tmpfs mounted above, and is empty.
        docker_run_args += ["--workdir", "/tmp"]
    docker_run_args += [image_tag, *_containerize_launch_command(launch_command)]
    transport = StdioTransport(command="docker", args=docker_run_args)

    start = time.monotonic()
    try:
        async with asyncio.timeout(timeout_seconds):
            async with Client(transport) as client:
                result = await client.call_tool(tool_name, arguments)
        duration_ms = int((time.monotonic() - start) * 1000)
        return result.data, duration_ms
    finally:
        # Killing the local `docker run` CLI client (e.g. via the timeout
        # above) does NOT stop the actual container -- containers are
        # supervised by dockerd/containerd, decoupled from the attached
        # client process. Without this, a hung/malicious tool call can
        # leave an orphaned, indefinitely-running container behind a
        # timeout that looks like it worked. Best-effort and swallowed:
        # the container has very likely already exited cleanly via --rm,
        # in which case this just no-ops, and cleanup must never mask the
        # real result/exception from the try block above.
        try:
            await _run_subprocess("docker", "kill", container_name, timeout_seconds=10.0)
        except Exception:
            pass


async def run_mcp_sandbox_test(
    *,
    local_path: str,
    launch_command: List[str],
    tool_name: str,
    sample_input: Dict[str, Any],
    timeout_seconds: float = 90.0,
    build_timeout_seconds: float = 180.0,
    memory_limit: str = "512m",
    cpus: str = "1.0",
    pids_limit: int = 128,
) -> SandboxResult:
    if not is_docker_available():
        return SandboxResult(
            passed=False,
            evidence_summary="Docker is not available on this host — required for MCP-native sandbox testing.",
            raw_output="",
            duration_ms=0,
        )

    start = time.monotonic()
    try:
        data, duration_ms = await _build_and_call(
            local_path=local_path, launch_command=launch_command, tool_name=tool_name, arguments=sample_input,
            allow_network=False, timeout_seconds=timeout_seconds, build_timeout_seconds=build_timeout_seconds,
            memory_limit=memory_limit, cpus=cpus, pids_limit=pids_limit,
        )
        return SandboxResult(
            passed=True,
            evidence_summary=(
                f"Sandbox run (network=none, memory={memory_limit}, cpus={cpus}): "
                f"called tool '{tool_name}' with {sample_input!r}, real result received in {duration_ms}ms."
            ),
            raw_output=repr(data),
            duration_ms=duration_ms,
        )
    except (asyncio.TimeoutError, TimeoutError):
        duration_ms = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            passed=False,
            evidence_summary=f"Sandbox run timed out after {timeout_seconds}s calling '{tool_name}'.",
            raw_output="",
            duration_ms=duration_ms,
        )
    except Exception as e:  # noqa: BLE001 — a failed build/tool-call is evidence too, not a crash
        duration_ms = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            passed=False,
            evidence_summary=f"Sandbox run failed calling '{tool_name}': {type(e).__name__}: {e}",
            raw_output=str(e),
            duration_ms=duration_ms,
        )


async def run_mcp_live_call(
    *,
    local_path: str,
    launch_command: List[str],
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_seconds: float = 30.0,
    build_timeout_seconds: float = 180.0,
    memory_limit: str = "512m",
    cpus: str = "1.0",
    pids_limit: int = 128,
) -> Dict[str, Any]:
    """Live (post-activation) invocation of an already-sandbox-tested
    MCP-native capability — called from DynamicCapabilityConnector's
    executor (see orchestrate/onboarding/runtime_registry.py). Every call
    still runs in a fresh, resource-limited, read-only container (same
    isolation as the sandbox test), but with network allowed — the one
    deliberate difference from sandbox testing. Raises on failure rather
    than returning a SandboxResult: the connector's execute() already
    wraps every executor call in its own try/except and turns any
    exception into a FAILED CapabilityResponse, so there's no need for a
    second error-shape here."""
    if not is_docker_available():
        raise RuntimeError("Docker is not available on this host — required to invoke an onboarded MCP-native capability")

    data, _duration_ms = await _build_and_call(
        local_path=local_path, launch_command=launch_command, tool_name=tool_name, arguments=arguments,
        allow_network=True, timeout_seconds=timeout_seconds, build_timeout_seconds=build_timeout_seconds,
        memory_limit=memory_limit, cpus=cpus, pids_limit=pids_limit,
    )
    return data if isinstance(data, dict) else {"result": data}


_RAW_CODE_RUNNER_SRC = Path(__file__).parent / "vendor" / "raw_code_runner.py"
_RAW_CODE_RUNNER_VERSION = "1"  # bump to force-bust every raw_code image cache entry if the runner itself changes


def _raw_code_dockerfile(install_dependencies: bool) -> str:
    install_step = (
        "RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi\n"
        if install_dependencies else ""
    )
    return (
        "FROM python:3.12-slim\n"
        "WORKDIR /workspace\n"
        "COPY . /workspace\n"
        f"{install_step}"
        "COPY .ados-raw-code-runner.py /workspace/raw_code_runner.py\n"
    )


def _raw_code_image_tag(local_path: Path, install_dependencies: bool) -> str:
    """A raw content hash alone would let an install_dependencies=True
    build and an install_dependencies=False build for the same repo
    collide on one tag (that boolean changes what the Dockerfile does but
    touches no file inside local_path) — a real correctness bug, not a
    style nit, so it's folded into the tag alongside the runner version."""
    content_hash = _compute_build_context_hash(local_path)
    variant = "deps" if install_dependencies else "nodeps"
    suffix = content_hash if content_hash else uuid.uuid4().hex[:12]
    return f"ados-onboarding-rawcode-v{_RAW_CODE_RUNNER_VERSION}-{variant}-{suffix}"


async def _build_raw_code_image(
    local_path: Path, *, image_tag: str, install_dependencies: bool, build_timeout_seconds: float
) -> bool:
    """Returns True if a build subprocess actually ran, False on a cache
    hit — same contract as _build_image. Always generates its OWN
    Dockerfile, unlike the other two tracks — never trusts a target-repo
    Dockerfile even if one is present, since this needs the vendored
    runner script staged into the build context regardless, and trusting
    an arbitrary Dockerfile is a materially bigger step for a track whose
    entire point is running an unvetted, non-self-describing function."""
    if await _image_exists(image_tag):
        return False

    dockerfile_path = local_path / ".ados-raw-code.Dockerfile"
    runner_copy_path = local_path / ".ados-raw-code-runner.py"
    dockerfile_path.write_text(_raw_code_dockerfile(install_dependencies))
    runner_copy_path.write_bytes(_RAW_CODE_RUNNER_SRC.read_bytes())
    try:
        returncode, output = await _run_subprocess(
            "docker", "build", "-f", str(dockerfile_path), "-t", image_tag, str(local_path),
            timeout_seconds=build_timeout_seconds,
        )
        if returncode != 0:
            raise RuntimeError(f"docker build failed (exit {returncode}):\n{output[-4000:]}")
    finally:
        dockerfile_path.unlink(missing_ok=True)
        runner_copy_path.unlink(missing_ok=True)
    return True


async def _build_and_call_raw_code(
    *,
    local_path: str,
    entrypoint_path: str,
    function_name: str,
    arguments: Dict[str, Any],
    install_dependencies: bool,
    allow_network: bool,
    timeout_seconds: float,
    build_timeout_seconds: float,
    memory_limit: str,
    cpus: str,
    pids_limit: int,
) -> Tuple[Any, int]:
    """Shared core for both the raw_code sandbox test and the raw_code
    live call — NOT fastmcp.Client-based like _build_and_call, since
    raw_code isn't a persistent MCP stdio server, it's a one-shot call/
    response driven by vendor/raw_code_runner.py: JSON arguments piped in
    via stdin, one JSON line read back from stdout."""
    path = Path(local_path)
    image_tag = _raw_code_image_tag(path, install_dependencies)
    built = await _build_raw_code_image(
        path, image_tag=image_tag, install_dependencies=install_dependencies, build_timeout_seconds=build_timeout_seconds
    )
    _touch_image_cache_entry(image_tag)
    if built:
        await _enforce_image_cache_limit()

    container_name = f"ados-onboarding-run-{uuid.uuid4().hex[:12]}"
    docker_run_args = [
        "run", "-i", "--rm", f"--name={container_name}",
        f"--memory={memory_limit}",
        f"--memory-swap={memory_limit}",
        f"--cpus={cpus}",
        f"--pids-limit={pids_limit}",
        "--read-only",
        "--tmpfs", "/tmp:rw,size=64m",
        *_HARDENED_RUN_FLAGS,
    ]
    if not allow_network:
        docker_run_args.append("--network=none")
    docker_run_args += [image_tag, "python", "raw_code_runner.py", entrypoint_path, function_name]

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", *docker_run_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(json.dumps(arguments).encode()), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"raw_code call timed out after {timeout_seconds}s calling {function_name!r}")
        duration_ms = int((time.monotonic() - start) * 1000)
        # raw_code_runner.py exits non-zero on every error path (including
        # ones where it still wrote a clean {"error": ...} line to stdout
        # first) -- check stdout for that clean payload BEFORE falling
        # back to a generic exit-code-based message, so real errors
        # (unknown function, non-serializable result, etc.) surface with
        # their real reason instead of an empty "exited 1: ".
        lines = [line for line in stdout.decode(errors="replace").strip().splitlines() if line.strip()]
        payload = None
        if lines:
            try:
                payload = json.loads(lines[-1])
            except json.JSONDecodeError:
                payload = None

        if isinstance(payload, dict) and "error" in payload:
            raise RuntimeError(f"raw_code function {function_name!r} raised: {payload['error']}")
        if proc.returncode != 0 or payload is None:
            raise RuntimeError(f"raw_code runner exited {proc.returncode}: {stderr.decode(errors='replace')[-2000:]}")
        return payload.get("result"), duration_ms
    finally:
        try:
            await _run_subprocess("docker", "kill", container_name, timeout_seconds=10.0)
        except Exception:
            pass


async def run_raw_code_sandbox_test(
    *,
    local_path: str,
    entrypoint_path: str,
    function_name: str,
    sample_input: Dict[str, Any],
    install_dependencies: bool = False,
    timeout_seconds: float = 90.0,
    build_timeout_seconds: float = 180.0,
    memory_limit: str = "512m",
    cpus: str = "1.0",
    pids_limit: int = 128,
) -> SandboxResult:
    if not is_docker_available():
        return SandboxResult(
            passed=False,
            evidence_summary="Docker is not available on this host — required for raw_code sandbox testing.",
            raw_output="",
            duration_ms=0,
        )

    start = time.monotonic()
    try:
        data, duration_ms = await _build_and_call_raw_code(
            local_path=local_path, entrypoint_path=entrypoint_path, function_name=function_name,
            arguments=sample_input, install_dependencies=install_dependencies,
            allow_network=False, timeout_seconds=timeout_seconds, build_timeout_seconds=build_timeout_seconds,
            memory_limit=memory_limit, cpus=cpus, pids_limit=pids_limit,
        )
        return SandboxResult(
            passed=True,
            evidence_summary=(
                f"Sandbox run (network=none, memory={memory_limit}, cpus={cpus}): "
                f"called function '{function_name}' with {sample_input!r}, real result received in {duration_ms}ms."
            ),
            raw_output=repr(data),
            duration_ms=duration_ms,
        )
    except (asyncio.TimeoutError, TimeoutError):
        duration_ms = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            passed=False,
            evidence_summary=f"Sandbox run timed out after {timeout_seconds}s calling '{function_name}'.",
            raw_output="",
            duration_ms=duration_ms,
        )
    except Exception as e:  # noqa: BLE001 — a failed build/call is evidence too, not a crash
        duration_ms = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            passed=False,
            evidence_summary=f"Sandbox run failed calling '{function_name}': {type(e).__name__}: {e}",
            raw_output=str(e),
            duration_ms=duration_ms,
        )


async def run_raw_code_live_call(
    *,
    local_path: str,
    entrypoint_path: str,
    function_name: str,
    arguments: Dict[str, Any],
    install_dependencies: bool = False,
    timeout_seconds: float = 30.0,
    build_timeout_seconds: float = 180.0,
    memory_limit: str = "512m",
    cpus: str = "1.0",
    pids_limit: int = 128,
) -> Dict[str, Any]:
    """Live (post-activation) invocation — same isolation as the sandbox
    test but with network allowed, mirroring run_mcp_live_call's own
    reasoning. Raises on failure rather than returning a SandboxResult:
    DynamicCapabilityConnector.execute() already wraps every executor call
    in its own try/except."""
    if not is_docker_available():
        raise RuntimeError("Docker is not available on this host — required to invoke an onboarded raw_code capability")

    data, _duration_ms = await _build_and_call_raw_code(
        local_path=local_path, entrypoint_path=entrypoint_path, function_name=function_name,
        arguments=arguments, install_dependencies=install_dependencies,
        allow_network=True, timeout_seconds=timeout_seconds, build_timeout_seconds=build_timeout_seconds,
        memory_limit=memory_limit, cpus=cpus, pids_limit=pids_limit,
    )
    return data if isinstance(data, dict) else {"result": data}


def _build_openapi_url(base_url: str, path_template: str, arguments: Dict[str, Any]) -> str:
    url = base_url.rstrip("/") + "/" + path_template.lstrip("/")
    for key, value in arguments.items():
        url = url.replace("{" + key + "}", str(value))
    return url


async def run_openapi_sandbox_test(
    *,
    test_base_url: str,
    method: str,
    path_template: str,
    sample_input: Dict[str, Any],
    acknowledge_live_call: bool,
    timeout_seconds: float = 30.0,
    transport: Optional["httpx.AsyncBaseTransport"] = None,
) -> SandboxResult:
    """No Docker isolation is possible here — the capability's entire point
    is reaching a real external API. acknowledge_live_call standing in for
    isolation is enforced by the caller (the router, Turn 4) requiring it
    explicitly in the request before this ever runs; this function still
    refuses to proceed without it as a second, independent guard rather
    than trusting the caller alone. Always calls test_base_url — never the
    capability's production base_url (see run_openapi_live_call) — so
    verification during onboarding can never accidentally reach prod.
    transport is injectable (httpx.MockTransport) so tests don't need a
    real external target — same pattern as ServiceNowConnector/SAPConnector."""
    if not acknowledge_live_call:
        return SandboxResult(
            passed=False,
            evidence_summary="OpenAPI sandbox test requires acknowledge_live_call=true — this is a real HTTP call, not an isolated one.",
            raw_output="",
            duration_ms=0,
        )

    import httpx

    start = time.monotonic()
    url = _build_openapi_url(test_base_url, path_template, sample_input)

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
            response = await client.request(method.upper(), url, json=sample_input if method.upper() != "GET" else None)
        duration_ms = int((time.monotonic() - start) * 1000)
        passed = response.status_code < 500
        return SandboxResult(
            passed=passed,
            evidence_summary=(
                f"Live sandbox call against declared test URL: {method.upper()} {url} -> "
                f"{response.status_code} in {duration_ms}ms."
            ),
            raw_output=response.text[:2000],
            duration_ms=duration_ms,
        )
    except httpx.HTTPError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        return SandboxResult(
            passed=False,
            evidence_summary=f"Live sandbox call failed: {type(e).__name__}: {e}",
            raw_output=str(e),
            duration_ms=duration_ms,
        )


async def run_openapi_live_call(
    *,
    base_url: str,
    method: str,
    path_template: str,
    arguments: Dict[str, Any],
    timeout_seconds: float = 30.0,
    transport: Optional["httpx.AsyncBaseTransport"] = None,
) -> Dict[str, Any]:
    """Live (post-activation) invocation — deliberately targets base_url
    (the capability's real/production endpoint, set at synthesize() time),
    never test_base_url. No Docker isolation here either, same reasoning as
    run_openapi_sandbox_test: the whole point of an OpenAPI-derived
    capability is reaching a real external system. Raises on failure
    rather than returning a SandboxResult — DynamicCapabilityConnector.
    execute() already wraps every executor call in its own try/except."""
    import httpx

    url = _build_openapi_url(base_url, path_template, arguments)
    async with httpx.AsyncClient(timeout=timeout_seconds, transport=transport) as client:
        response = await client.request(method.upper(), url, json=arguments if method.upper() != "GET" else None)
    if response.status_code >= 400:
        raise RuntimeError(f"{method.upper()} {url} -> {response.status_code}: {response.text[:500]}")
    try:
        return response.json()
    except ValueError:
        return {"status_code": response.status_code, "text": response.text[:2000]}
