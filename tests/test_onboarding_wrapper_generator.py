"""orchestrate/onboarding/wrapper_generator.py — Turn 2, mapping a
DiscoveredTool (inspector.py) into a SynthesizedAction. No code generation
in scope for either track (see wrapper_generator.py's module docstring for
why) — these are pure mapping tests. The OpenAPI tests shell out to the
real vendored openapi-mcp-generator-1 (orchestrate/onboarding/vendor/) —
not mocked, since the whole point of that dependency is real per-operation
schema extraction inspector.py's lightweight parse can't do."""

from pathlib import Path

import pytest

from orchestrate.onboarding.models import DiscoveredTool, OnboardingTrack
from orchestrate.onboarding.wrapper_generator import synthesize_mcp_action, synthesize_openapi_action, synthesize_raw_code_action

_OPENAPI_FIXTURE_SPEC = str(Path(__file__).parent / "fixtures" / "openapi_sample" / "openapi.json")


def test_synthesize_mcp_action_maps_tool_into_synthesized_action():
    tool = DiscoveredTool(
        name="add_numbers",
        description="Add two integers and return the sum.",
        input_schema={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    )
    action = synthesize_mcp_action(
        tool,
        capability_id="echo-sample.add_numbers",
        domain="support",
        version="1.0.0",
        estimated_cost_usd=0.0,
        launch_command=["python", "server.py"],
        local_path="/tmp/ados-onboarding/echo-sample",
    )

    assert action.key == "add_numbers"
    assert action.description == "Add two integers and return the sum."
    assert action.capability_id == "echo-sample.add_numbers"
    assert action.domain == "support"
    assert action.track is OnboardingTrack.MCP_NATIVE
    assert action.runtime["launch_command"] == ["python", "server.py"]
    assert action.runtime["tool_name"] == "add_numbers"
    assert action.runtime["input_schema"] == tool.input_schema
    assert action.runtime["local_path"] == "/tmp/ados-onboarding/echo-sample"


def test_synthesize_mcp_action_falls_back_to_tool_name_when_no_description():
    tool = DiscoveredTool(name="ping", description="")
    action = synthesize_mcp_action(
        tool, capability_id="x.ping", domain="it", version="1.0.0", estimated_cost_usd=0.0,
        launch_command=["python", "s.py"], local_path="/tmp/x",
    )
    assert action.description == "ping"


@pytest.mark.asyncio
async def test_synthesize_openapi_action_extracts_real_schema_via_vendored_generator():
    action = await synthesize_openapi_action(
        _OPENAPI_FIXTURE_SPEC,
        "read_ticket",
        capability_id="zendesk.read_ticket",
        domain="support",
        version="1.0.0",
        estimated_cost_usd=0.0,
        test_base_url="https://staging.zendesk.example.com",
    )

    assert action.key == "read_ticket"
    assert action.description == "Fetch a support ticket by id"
    assert action.capability_id == "zendesk.read_ticket"
    assert action.track is OnboardingTrack.OPENAPI
    assert action.runtime["method"] == "get"
    assert action.runtime["path_template"] == "/tickets/{ticket_id}"
    assert action.runtime["input_schema"]["required"] == ["ticket_id"]
    assert action.runtime["test_base_url"] == "https://staging.zendesk.example.com"
    # No production_base_url given -> falls back to the spec's own default
    # server resolution, distinct from (and never equal to) the test URL.
    assert action.runtime["base_url"] != "https://staging.zendesk.example.com"


@pytest.mark.asyncio
async def test_synthesize_openapi_action_respects_explicit_production_base_url():
    action = await synthesize_openapi_action(
        _OPENAPI_FIXTURE_SPEC,
        "create_ticket",
        capability_id="zendesk.create_ticket",
        domain="support",
        version="1.0.0",
        estimated_cost_usd=0.0,
        test_base_url="https://staging.zendesk.example.com",
        production_base_url="https://api.zendesk.example.com",
    )
    assert action.runtime["base_url"] == "https://api.zendesk.example.com"
    assert action.runtime["test_base_url"] == "https://staging.zendesk.example.com"


def test_synthesize_raw_code_action_maps_tool_into_synthesized_action():
    tool = DiscoveredTool(
        name="add_numbers",
        description="Add two integers and return the sum.",
        input_schema={"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]},
        runtime={"entrypoint_path": "tool.py", "function_name": "add_numbers"},
    )
    action = synthesize_raw_code_action(
        tool, capability_id="local.add_numbers", domain="ops", version="1.0.0", estimated_cost_usd=0.0,
        local_path="/tmp/ados-onboarding/raw-code-sample", entrypoint_path="tool.py",
    )

    assert action.key == "add_numbers"
    assert action.track is OnboardingTrack.RAW_CODE
    assert action.runtime["local_path"] == "/tmp/ados-onboarding/raw-code-sample"
    assert action.runtime["entrypoint_path"] == "tool.py"
    assert action.runtime["function_name"] == "add_numbers"
    assert action.runtime["input_schema"] == tool.input_schema
    assert action.runtime["install_dependencies"] is False  # default off


def test_synthesize_raw_code_action_respects_explicit_install_dependencies():
    tool = DiscoveredTool(name="f", description="")
    action = synthesize_raw_code_action(
        tool, capability_id="x.f", domain="ops", version="1.0.0", estimated_cost_usd=0.0,
        local_path="/tmp/x", entrypoint_path="tool.py", install_dependencies=True,
    )
    assert action.runtime["install_dependencies"] is True


@pytest.mark.asyncio
async def test_synthesize_openapi_action_rejects_unknown_operation_id():
    with pytest.raises(ValueError, match="not found"):
        await synthesize_openapi_action(
            _OPENAPI_FIXTURE_SPEC,
            "delete_everything",
            capability_id="x.y",
            domain="support",
            version="1.0.0",
            estimated_cost_usd=0.0,
            test_base_url="https://staging.example.com",
        )
