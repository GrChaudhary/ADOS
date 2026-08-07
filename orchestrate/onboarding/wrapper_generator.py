"""
Turn 2 of the onboarding pipeline (§8.4 step 2, "wrap") — but for the
MCP-native and OpenAPI tracks specifically there's no code to *generate*:
both call an existing self-describing interface, so "wrapping" here means
mapping one admin-selected DiscoveredTool (inspector.py, Turn 1) into the
shape the rest of the pipeline needs — risk_proposal.py,
CapabilityManifestRegistry.propose(), and eventually
DynamicCapabilityConnector's dispatch (via SynthesizedAction.runtime).

This is a deliberate scope reduction, not a shortcut: ADOS has zero
precedent for writing generated/fetched source to disk and executing it
(see the ADOS_OBSIDIAN vault TODO's raw-code deferral) — both tracks here
sidestep that entirely by only ever calling code that already existed
before the onboarding pipeline touched it.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import DiscoveredTool, OnboardingTrack, SynthesizedAction

_SHIM_PATH = Path(__file__).parent / "vendor" / "get_tools_shim.mjs"


def synthesize_mcp_action(
    tool: DiscoveredTool,
    *,
    capability_id: str,
    domain: str,
    version: str,
    estimated_cost_usd: float,
    launch_command: List[str],
    local_path: str,
) -> SynthesizedAction:
    """local_path is carried through into runtime so a live, post-
    activation call (sandbox_runner.run_mcp_live_call, via
    runtime_registry.py's executor) can spin up a fresh, isolated
    container every time — see sandbox_runner._build_and_call's docstring:
    the container is always fresh, but the underlying image is now
    content-hash-cached/reused across calls rather than rebuilt from
    scratch every time."""
    return SynthesizedAction(
        key=tool.name,
        description=tool.description or tool.name,
        capability_id=capability_id,
        domain=domain,
        version=version,
        estimated_cost_usd=estimated_cost_usd,
        track=OnboardingTrack.MCP_NATIVE,
        runtime={
            "launch_command": launch_command,
            "tool_name": tool.name,
            "input_schema": tool.input_schema,
            "local_path": local_path,
        },
    )


def synthesize_raw_code_action(
    tool: DiscoveredTool,
    *,
    capability_id: str,
    domain: str,
    version: str,
    estimated_cost_usd: float,
    local_path: str,
    entrypoint_path: str,
    install_dependencies: bool = False,
) -> SynthesizedAction:
    """install_dependencies mirrors the OpenAPI track's
    acknowledge_live_call explicit-consent pattern: the sandbox build
    phase only runs `pip install -r requirements.txt` for a raw_code
    target if the admin opts in here, at synthesize time (default off) —
    an unvetted arbitrary function gets a materially higher bar than the
    other two tracks' implicit dependency installation."""
    return SynthesizedAction(
        key=tool.name,
        description=tool.description or tool.name,
        capability_id=capability_id,
        domain=domain,
        version=version,
        estimated_cost_usd=estimated_cost_usd,
        track=OnboardingTrack.RAW_CODE,
        runtime={
            "local_path": local_path,
            "entrypoint_path": entrypoint_path,
            "function_name": tool.name,
            "input_schema": tool.input_schema,
            "install_dependencies": install_dependencies,
        },
    )


async def _run_shim(spec_path_or_url: str, base_url: Optional[str] = None) -> List[Dict[str, Any]]:
    """Shells out to the vendored openapi-mcp-generator-1 (TypeScript,
    Node — see orchestrate/onboarding/vendor/) for real per-operation
    parameter/request-body schema extraction that inspector.py's
    lightweight direct spec parse deliberately doesn't attempt. This is
    genuine cross-process/cross-language infra, not hidden: callers must
    check shutil.which("node") themselves first (both synthesize_openapi_
    action below and sandbox_runner.py's OpenAPI path do)."""
    args = ["node", str(_SHIM_PATH), spec_path_or_url]
    if base_url:
        args.append(base_url)
    proc = await asyncio.create_subprocess_exec(*args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"openapi-mcp-generator shim failed: {stderr.decode(errors='replace').strip()}")
    return json.loads(stdout)


async def synthesize_openapi_action(
    spec_path: str,
    operation_id: str,
    *,
    capability_id: str,
    domain: str,
    version: str,
    estimated_cost_usd: float,
    test_base_url: str,
    production_base_url: Optional[str] = None,
) -> SynthesizedAction:
    """test_base_url is sandbox-only — sandbox_runner.run_openapi_sandbox_test
    always uses it, forced, so verification can never accidentally reach
    production. production_base_url is what live, post-activation calls use
    (runtime_registry.py's openapi executor); if not given, falls back to
    whichever server URL the spec itself declares (resolved by calling the
    shim with no override) — for many real APIs that IS the production
    endpoint, since that's what an OpenAPI spec's `servers[0].url` is for."""
    if shutil.which("node") is None:
        raise RuntimeError("Node.js is not available on this host — required for OpenAPI onboarding (openapi-mcp-generator-1)")

    tools = await _run_shim(spec_path, production_base_url)
    matching = next((t for t in tools if t.get("operationId") == operation_id), None)
    if matching is None:
        raise ValueError(f"operation_id {operation_id!r} not found in {spec_path}")

    return SynthesizedAction(
        key=matching["name"],
        description=matching.get("description") or matching["name"],
        capability_id=capability_id,
        domain=domain,
        version=version,
        estimated_cost_usd=estimated_cost_usd,
        track=OnboardingTrack.OPENAPI,
        runtime={
            "method": matching["method"],
            "path_template": matching["pathTemplate"],
            "input_schema": matching.get("inputSchema") or {},
            "base_url": matching.get("baseUrl"),
            "test_base_url": test_base_url,
        },
    )
