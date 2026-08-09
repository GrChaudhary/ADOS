"""
Regression tests for the Prime Agent runtime image's kernel contract.

WHY THIS FILE EXISTS
--------------------
Prime Agent's only tool is a persistent IPython kernel. `PRIME_AGENT_KERNEL_PYTHON`
lets us pin that kernel at build time instead of letting the agent bootstrap one
over the network at first run — but the override is *validated*, not trusted.
`ensureKernelPythonUncached()` in
prime-agent/packages/coding-agent/src/core/kernel/bootstrap.ts requires:

    1. ipykernel imports
    2. prime-agent-runtime satisfies RUNTIME_READY_CHECK
    3. EVERY package in DEFAULT_RLM_EXTRA_PACKAGES imports

and throws if any part is missing.

An image satisfying only (1) and (2) looks entirely healthy from the outside:
the venv exists, `import rlm` works, the container starts, the model runs, tool
calls are attempted. But the check runs lazily on FIRST TOOL USE, so the failure
surfaces only as every tool execution erroring identically. A real acceptance run
against such an image produced 18 tool executions, 18 failures, zero capability
requests — and a fluent, confidently fabricated root-cause report naming a disk
-space exhaustion that appeared nowhere in the incident data it never managed to
read.

That is the failure this file exists to prevent, and it is worth being precise
about which failure it is. Not "the container was broken" — the container was
fine. The gap between "the runtime can act" and "the runtime can produce
plausible prose" is exactly the gap ADOS's acceptance rules are built to detect,
and this test closes it one layer earlier, at build time.

The package list is PARSED FROM PRIME AGENT'S OWN SOURCE rather than copied here,
so a future upstream version that adds a required package fails this test instead
of silently disabling the runtime's ability to do anything at all.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ADOS_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _ADOS_ROOT / "infrastructure" / "prime-runtime" / "Dockerfile"
_BOOTSTRAP_TS = (
    _ADOS_ROOT.parent
    / "prime-agent"
    / "packages"
    / "coding-agent"
    / "src"
    / "core"
    / "kernel"
    / "bootstrap.ts"
)

IMAGE_TAG = "ados-prime-runtime:0.7.1"

_needs_source = pytest.mark.skipif(
    not _BOOTSTRAP_TS.is_file(),
    reason=f"Prime Agent source not checked out at {_BOOTSTRAP_TS.parent}",
)


def _ts_array(name: str, source: str) -> str:
    """Extracts the body of a top-level `const <name> = [...]` from TypeScript."""
    match = re.search(rf"const {name}\s*=\s*\[(.*?)\n\];", source, re.DOTALL)
    assert match, f"{name} not found in bootstrap.ts — upstream layout changed"
    return match.group(1)


def required_kernel_packages() -> list[tuple[str, str]]:
    """(pip package, import name) for every DEFAULT_RLM_EXTRA_PACKAGES entry."""
    body = _ts_array("DEFAULT_RLM_EXTRA_PACKAGES", _BOOTSTRAP_TS.read_text())
    packages = re.findall(r'uvArg:\s*"([^"]+)".*?importName:\s*"([^"]+)"', body)
    assert packages, "DEFAULT_RLM_EXTRA_PACKAGES parsed but empty"
    return packages


def runtime_ready_check() -> str:
    """Prime Agent's own RUNTIME_READY_CHECK, with its one template
    substitution resolved, so the test asserts the real contract rather than a
    paraphrase of it that can drift."""
    source = _BOOTSTRAP_TS.read_text()
    match = re.search(r"const RUNTIME_READY_CHECK = `(.*?)`;", source, re.DOTALL)
    assert match, "RUNTIME_READY_CHECK not found in bootstrap.ts"
    methods = re.findall(r'"([^"]+)"', _ts_array("REQUIRED_HARNESS_METHODS", source))
    return match.group(1).replace(
        "${JSON.stringify(REQUIRED_HARNESS_METHODS)}", json.dumps(methods)
    )


@_needs_source
def test_dockerfile_installs_every_package_the_kernel_override_requires():
    """The static half: catches drift without needing Docker or a built image.

    Fails on the exact condition that disabled the runtime — a kernel venv that
    imports rlm but not the packages Prime Agent insists on before it will use
    that kernel at all.
    """
    dockerfile = _DOCKERFILE.read_text()
    missing = [pkg for pkg, _ in required_kernel_packages() if not re.search(rf"\b{re.escape(pkg)}\b", dockerfile)]
    assert not missing, (
        f"{_DOCKERFILE.name} does not install: {missing}. Prime Agent validates "
        "PRIME_AGENT_KERNEL_PYTHON against DEFAULT_RLM_EXTRA_PACKAGES and refuses "
        "the pinned kernel if any is absent — every tool execution then fails "
        "while the container still looks healthy."
    )


@_needs_source
def test_system_prompt_promises_the_model_these_packages_are_installed():
    """The same list is advertised to the model as 'Pre-installed Python
    packages' (core/prompts/rlm.ts), so a partial install does not merely break
    the kernel — it makes the agent's own instructions untrue."""
    prompt_source = (
        _BOOTSTRAP_TS.parent.parent / "prompts" / "rlm.ts"
    )
    if not prompt_source.is_file():
        pytest.skip("prompts/rlm.ts not found — upstream layout changed")
    assert "DEFAULT_RLM_EXTRA_IMPORT_LABELS" in prompt_source.read_text()


# --- the live half: assert against the actual built image --------------------

def _docker_image_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        out = subprocess.run(
            ["docker", "images", "-q", IMAGE_TAG],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return bool(out.stdout.strip())


_needs_image = pytest.mark.skipif(
    os.environ.get("ADOS_SKIP_DOCKER_TESTS") == "1" or not _docker_image_available(),
    reason=f"{IMAGE_TAG} not built (run `python -m orchestrate.runtime.prime_image`)",
)


def _in_image(*script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "/home/prime/kernel-venv/bin/python",
         IMAGE_TAG, *script],
        capture_output=True, text=True, timeout=180,
    )


@_needs_source
@_needs_image
def test_built_image_satisfies_the_kernel_python_override_contract():
    """Runs Prime Agent's three checks against the real image, the same way
    bootstrap.ts runs them. This is the test that would actually have caught the
    18/18 failure: the static test above proves the Dockerfile *says* the right
    thing, this one proves the image *is* the right thing.
    """
    imports = ["ipykernel"] + [imp for _, imp in required_kernel_packages()]
    result = _in_image("-c", "; ".join(f"import {name}" for name in imports))
    assert result.returncode == 0, (
        f"kernel python cannot import the required set: {result.stderr.strip()[:500]}"
    )

    ready = _in_image("-c", runtime_ready_check())
    assert ready.returncode == 0, (
        f"kernel python fails Prime Agent's RUNTIME_READY_CHECK: {ready.stderr.strip()[:500]}"
    )


@_needs_image
def test_built_image_can_import_the_ados_capability_skill():
    """The ADOS skill is the runtime's only route back into ADOS. A missing or
    root-owned install here means the agent can reason but never act — which,
    left undetected, is precisely the state in which it invents its evidence."""
    result = _in_image("-c", "import ados; assert hasattr(ados, 'Ados')")
    assert result.returncode == 0, result.stderr.strip()[:500]
