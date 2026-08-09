"""
Regression test for the ADOS skill's response decoding.

The skill runs inside the Prime Agent container, not in this process, so the
module itself is not importable here. What IS testable — and what actually
broke — is the decoding contract: `rlm.mcp_base._parse_result` returns a dict
when the MCP response carries `structuredContent`, and a JSON **string** when
the server sends only text blocks. FastMCP emits text-only content for the
gateway's tools, so the skill received a str and called `.get("status")` on it:

    AttributeError: 'str' object has no attribute 'get'

raised inside the skill, on every call. The failure mode is the interesting
part: ADOS had *already executed the capability* — three successful
FetchIncidentEvidence rows sat in the audit trail — and the agent never
received the answer. Work done, result lost.

This lifts `_decoded` out of the skill source and tests it directly, so the
container does not have to be built or running.
"""

import json
from pathlib import Path

import pytest

_SKILL = (
    Path(__file__).resolve().parents[2]
    / "infrastructure" / "prime-runtime" / "ados_skill" / "src" / "ados" / "__init__.py"
)


def _load_decoded():
    """Extract `_decoded` without importing the module — importing would pull
    in `rlm`, which only exists inside the runtime container."""
    source = _SKILL.read_text()
    start = source.index("def _decoded(")
    end = source.index("class CapabilityDenied")
    namespace: dict = {"json": json, "Any": object}
    exec(compile(source[start:end], str(_SKILL), "exec"), namespace)  # noqa: S102
    return namespace["_decoded"]


decoded = _load_decoded()

GATEWAY_RESPONSE = {
    "status": "executed",
    "request_id": "3b76fe71-3bb4-446f-9c05-65ba5903c305",
    "policy_tier": 0,
    "result": {
        "ok": True,
        "capability": "FetchIncidentEvidence",
        "outcome": {
            "status": "succeeded",
            "connector": "mission-evidence",
            "output": {"evidence": {"incident_id": "SYN-4417"}},
        },
    },
}


def test_a_json_string_response_is_decoded():
    """The shape that broke it: text-only MCP content."""
    assert decoded(json.dumps(GATEWAY_RESPONSE)) == GATEWAY_RESPONSE


def test_a_dict_response_passes_through():
    """The structuredContent shape. Both must work — which one arrives is a
    property of the server's schema declarations and can change without notice."""
    assert decoded(GATEWAY_RESPONSE) is GATEWAY_RESPONSE


def test_the_documented_access_path_survives_decoding():
    """The exact expression the mission prompt tells the model to use. If this
    breaks, every mission prompt in the docs is wrong."""
    r = decoded(json.dumps(GATEWAY_RESPONSE))
    assert r["result"]["outcome"]["output"]["evidence"]["incident_id"] == "SYN-4417"


def test_status_is_reachable_after_decoding():
    """`.get("status")` on the decoded result is what raised AttributeError."""
    assert decoded(json.dumps(GATEWAY_RESPONSE)).get("status") == "executed"


def test_bytes_are_decoded():
    assert decoded(json.dumps(GATEWAY_RESPONSE).encode()) == GATEWAY_RESPONSE


def test_non_json_text_is_returned_untouched():
    """Don't guess. A server that returns prose should surface that prose, not
    a parse error that hides it."""
    assert decoded("gateway unreachable") == "gateway unreachable"


@pytest.mark.parametrize("value", [{}, [], 0, None, False])
def test_falsy_but_valid_payloads_are_preserved(value):
    """An empty dict is a real result, not a missing one."""
    assert decoded(value) == value


# --- edge cases found by re-reading rlm.mcp_base._parse_result ----------------

def test_a_json_array_string_decodes_to_a_list():
    """`capabilities()` goes through the same path and returns a LIST, not a
    dict. Decoding must not assume the top level is an object."""
    caps = [{"capability": "FetchIncidentEvidence", "description": "..."}]
    assert decoded(json.dumps(caps)) == caps


def test_a_denied_response_survives_decoding():
    """The denial path is the one place a decode failure would be silently
    dangerous: `res.get("status") == "denied"` raising AttributeError turns a
    refusal into a traceback, and an agent that cannot read a denial may keep
    looking for another route."""
    denial = {"status": "denied", "request_id": "x", "reason": "not in this mission's grant"}
    assert decoded(json.dumps(denial))["status"] == "denied"


def test_multiple_text_blocks_joined_by_the_shim_are_not_mangled():
    """_parse_result joins several text blocks with "\\n". The join is usually
    not valid JSON, and guessing at it would be worse than surfacing it — the
    caller sees the server's actual words instead of a parse error."""
    joined = '{"status": "executed"}\n{"status": "executed"}'
    assert decoded(joined) == joined


def test_whitespace_padded_json_still_decodes():
    assert decoded('  \n {"status": "executed"} \n ') == {"status": "executed"}


def test_a_json_scalar_string_is_not_mistaken_for_a_payload():
    """json.loads('"hello"') is the string 'hello', not an object. Callers do
    `.get(...)` on this, so the important property is simply that decoding is
    deterministic and does not raise here — the AttributeError that follows is
    a truthful signal that the server sent something unusable."""
    assert decoded('"hello"') == "hello"
