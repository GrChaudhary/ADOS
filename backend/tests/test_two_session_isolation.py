"""
Two concurrent missions, and the wall between them — measured, not configured.

WHY THIS IS SEPARATE FROM THE EGRESS TESTS
------------------------------------------
`test_runtime_egress_boundary.py` stands one session up and proves it can reach
its allowlist and nothing else. That is a statement about the outside world. It
says nothing about a second session, because there was never a second one in
the room: with a single boundary running, "cannot reach the other mission's
runtime" is trivially true and completely untested.

Per-session networks are the design (`egress.py`: "A shared internal network
would let two concurrent missions' runtimes reach each other"), and the design
was asserted only by reading the `docker network create` arguments. A test that
reads configuration and concludes isolation is the same class of mistake as an
agent reading its own narrative and concluding success — so every claim here is
a connection attempt made from inside a live container.

WHAT IS PROVED FROM INSIDE EACH CONTAINER
-----------------------------------------
* it reaches its OWN permitted destination, by name, through its own relay
* it reaches its own relay's address directly — the positive control that makes
  every "BLOCKED" below meaningful rather than the answer of a container with
  no networking at all
* it cannot reach the other session's runtime container, the other session's
  relay, or the other session's permitted destination — by address, so the
  result does not depend on DNS being absent
* the other session's destination name does not resolve

And, at the credential layer, that neither live session's token can act as the
other: the tokens used are the ones actually handed to these two containers.

MARKED `docker`: deselected by default (`-m 'not external and not docker'`).
"""

import json
import shutil
import subprocess
import uuid

import pytest
from sqlalchemy import text

from backend.app import mcp_gateway
from backend.app.mcp_gateway import hash_token, request_capability
from contracts import Capability
from db.engine import async_session_factory
from db.models.mission import MissionRow, RuntimeSessionRow
from orchestrate.runtime.egress import Destination, EgressBoundary
from orchestrate.runtime.prime import mint_session_token, token_expiry

RUNTIME_IMAGE = "ados-prime-runtime:0.7.1"
RELAY_IMAGE = "ados-egress-relay:1"
LISTENER_IMAGE = "python:3.12-alpine"


def _images_present() -> bool:
    if not shutil.which("docker"):
        return False
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True,
    ).stdout
    return RUNTIME_IMAGE in out and RELAY_IMAGE in out


def _ip_of(container: str) -> str:
    out = subprocess.run(
        ["docker", "inspect", "-f",
         "{{range $k, $v := .NetworkSettings.Networks}}{{$v.IPAddress}} {{end}}", container],
        capture_output=True, text=True, timeout=60,
    ).stdout.split()
    assert out, f"no address for {container}"
    return out[0]


PROBE = r"""
import json, socket, sys, urllib.request

targets = json.loads(sys.argv[1])
out = {}

def reach(host, port, timeout=4):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return "REACHABLE"
    except Exception as e:
        return f"BLOCKED({type(e).__name__})"

# Counted separately, because they answer different questions. The claim is
# "no DEFAULT route" — a destination of 00000000 in /proc/net/route. The
# on-link route for the container's own subnet is expected and is what lets it
# reach its relay at all, so a total of 1 is the correct, healthy reading.
routes = [r for r in open("/proc/net/route").read().splitlines()[1:] if r.strip()]
out["ROUTE_COUNT"] = len(routes)
out["DEFAULT_ROUTES"] = len([r for r in routes if r.split()[1] == "00000000"])
for label, (host, port) in targets.items():
    out[label] = reach(host, port)

try:
    socket.gethostbyname(targets["OTHER_DESTINATION_BY_NAME"][0])
    out["OTHER_NAME_RESOLVES"] = "YES"
except Exception as e:
    out["OTHER_NAME_RESOLVES"] = f"NO({type(e).__name__})"

try:
    r = urllib.request.urlopen(
        "http://%s:%d/" % tuple(targets["OWN_DESTINATION_BY_NAME"]), timeout=8
    )
    out["OWN_HTTP"] = r.status
except Exception as e:
    out["OWN_HTTP"] = type(e).__name__

print(json.dumps(out))
"""


def _probe(container: str, targets: dict) -> dict:
    result = subprocess.run(
        ["docker", "exec", container, "/home/prime/kernel-venv/bin/python",
         "-c", PROBE, json.dumps(targets)],
        capture_output=True, text=True, timeout=180,
    )
    assert result.stdout.strip(), f"probe produced nothing: {result.stderr[-800:]}"
    return json.loads(result.stdout.strip())


class _Session:
    """One live session: a permitted destination, a boundary, a container."""

    def __init__(self, label: str):
        self.label = label
        self.id = uuid.uuid4().hex[:12]
        self.listener = f"ados-iso-dest-{self.id}"
        self.container = f"ados-iso-rt-{self.id}"
        self.upstream_net = f"ados-iso-up-{self.id}"
        self.boundary = None

    def start(self, loop):
        subprocess.run(["docker", "network", "create", self.upstream_net],
                       capture_output=True, timeout=60)
        subprocess.run(
            ["docker", "run", "-d", "--name", self.listener, "--network", self.upstream_net,
             LISTENER_IMAGE, "python3", "-m", "http.server", "8077"],
            capture_output=True, text=True, check=True, timeout=180,
        )
        self.boundary = EgressBoundary(self.id, [Destination(self.listener, 8077)])
        loop.run_until_complete(self.boundary.start())
        subprocess.run(
            ["docker", "network", "connect", self.upstream_net, self.boundary.relay_container],
            capture_output=True, timeout=60,
        )
        subprocess.run(
            ["docker", "run", "-d", "--name", self.container, *self.boundary.container_args(),
             "--memory", "512m", "--pids-limit", "128", RUNTIME_IMAGE, "sleep", "600"],
            capture_output=True, text=True, check=True, timeout=180,
        )

    def stop(self, loop):
        for name in (self.container, self.listener):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=90)
        if self.boundary is not None:
            loop.run_until_complete(self.boundary.teardown())
        subprocess.run(["docker", "network", "rm", self.upstream_net],
                       capture_output=True, timeout=60)


@pytest.fixture
def two_live_sessions():
    """Two complete session boundaries, up at the same time."""
    if not _images_present():
        pytest.skip(f"needs {RUNTIME_IMAGE} and {RELAY_IMAGE} built locally")

    import asyncio

    loop = asyncio.new_event_loop()
    a, b = _Session("A"), _Session("B")
    try:
        a.start(loop)
        b.start(loop)
        yield a, b
    finally:
        a.stop(loop)
        b.stop(loop)
        loop.close()


def _targets_for(mine: _Session, theirs: _Session) -> dict:
    """The relay addresses come from `boundary.relay_ip`, not from inspecting
    the container.

    The relay is dual-homed, and `docker inspect` ranges its networks in sorted
    key order — which returns the UPSTREAM address first. Probing that one from
    the runtime would report BLOCKED for the entirely uninteresting reason that
    it is on a network the runtime was never meant to see, and the cross-session
    assertion would then be passing for the wrong reason. `relay_ip` is the
    internal-network address, i.e. the one `--add-host` actually points the
    runtime at. Caught by the positive control below.
    """
    return {
        "OWN_DESTINATION_BY_NAME": [mine.listener, 8077],
        "OWN_RELAY_BY_ADDRESS": [mine.boundary.relay_ip, 8077],
        "OTHER_RUNTIME_BY_ADDRESS": [_ip_of(theirs.container), 22],
        "OTHER_RELAY_BY_ADDRESS": [theirs.boundary.relay_ip, 8077],
        "OTHER_DESTINATION_BY_ADDRESS": [_ip_of(theirs.listener), 8077],
        "OTHER_DESTINATION_BY_NAME": [theirs.listener, 8077],
    }


@pytest.mark.docker
def test_each_session_reaches_its_own_allowlist_and_neither_reaches_the_other(
    two_live_sessions
):
    """Both directions, both containers, in one test.

    The blocked assertions on their own are satisfied by a container with no
    network at all — and by a relay that never finished starting, which is a
    bug this pairing has already caught once. `OWN_DESTINATION_BY_NAME` and
    `OWN_RELAY_BY_ADDRESS` are what make the rest mean something: the probe
    method works, addresses on the other side are simply not routable.
    """
    a, b = two_live_sessions
    seen = {}

    for mine, theirs in ((a, b), (b, a)):
        result = _probe(mine.container, _targets_for(mine, theirs))
        seen[mine.label] = result

        # No default route at all — the reason isolation holds, not the proof.
        # The single on-link route is expected: it is how the container reaches
        # its own relay, and a container with zero routes would make every
        # BLOCKED below meaningless.
        assert result["DEFAULT_ROUTES"] == 0, result
        assert result["ROUTE_COUNT"] == 1, f"expected only the on-link route: {result}"

        # Positive controls.
        assert result["OWN_DESTINATION_BY_NAME"] == "REACHABLE", (
            f"session {mine.label} cannot reach its own permitted destination: {result}"
        )
        assert result["OWN_HTTP"] == 200, result
        assert result["OWN_RELAY_BY_ADDRESS"] == "REACHABLE", (
            f"session {mine.label} cannot reach its own relay by address, so a "
            f"BLOCKED result below would not mean anything: {result}"
        )

        # The wall, probed by ADDRESS so DNS is not what is being tested.
        assert result["OTHER_RUNTIME_BY_ADDRESS"].startswith("BLOCKED"), (
            f"session {mine.label} reached session {theirs.label}'s runtime: {result}"
        )
        assert result["OTHER_RELAY_BY_ADDRESS"].startswith("BLOCKED"), (
            f"session {mine.label} reached session {theirs.label}'s relay: {result}"
        )
        assert result["OTHER_DESTINATION_BY_ADDRESS"].startswith("BLOCKED"), (
            f"session {mine.label} reached session {theirs.label}'s upstream: {result}"
        )
        assert result["OTHER_NAME_RESOLVES"].startswith("NO"), result

    print("\nsession A probes:", json.dumps(seen["A"], indent=2))
    print("session B probes:", json.dumps(seen["B"], indent=2))


@pytest.mark.docker
def test_the_two_sessions_are_on_different_networks_with_different_subnets(
    two_live_sessions
):
    """Supporting evidence, deliberately NOT the proof — the connectivity test
    above is. This exists so a failure there can be diagnosed: identical
    subnets would mean the addresses probed were never distinct."""
    a, b = two_live_sessions

    assert a.boundary.internal_network != b.boundary.internal_network

    def subnet(network):
        out = subprocess.run(
            ["docker", "network", "inspect", "-f", "{{range .IPAM.Config}}{{.Subnet}}{{end}}",
             network],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        return out

    assert subnet(a.boundary.internal_network) != subnet(b.boundary.internal_network)
    assert _ip_of(a.container) != _ip_of(b.container)


# --- the credential wall, using these two sessions' real tokens ---------------

@pytest.mark.docker
async def test_neither_live_sessions_token_can_act_as_the_other(two_live_sessions, monkeypatch):
    """Network isolation and credential isolation are different walls, and a
    system can have one without the other. These are the tokens actually
    handed to the two containers above."""
    a, b = two_live_sessions

    async with async_session_factory() as db:
        await db.execute(text("TRUNCATE missions, runtime_sessions, capability_requests CASCADE"))
        await db.commit()

    tokens = {}
    for session, capability in (
        (a, Capability.NOTIFY_IT_HELPDESK),
        (b, Capability.CREATE_CHANGE_REQUEST),
    ):
        async with async_session_factory() as db:
            mission = MissionRow(
                title=f"live session {session.label}", objective="o", domain="it",
                allowed_capabilities=[capability.value], status="running",
            )
            db.add(mission)
            await db.flush()
            token = mint_session_token()
            db.add(RuntimeSessionRow(
                mission_id=mission.mission_id, state="running",
                token_hash=hash_token(token), token_expires_at=token_expiry(600.0),
            ))
            await db.commit()
            tokens[session.label] = token

    def present(token):
        monkeypatch.setattr(
            mcp_gateway, "get_http_headers", lambda: {"authorization": f"Bearer {token}"}
        )

    # A holds a real, live, unexpired credential — and it is not B's.
    present(tokens["A"])
    assert (await mcp_gateway.list_capabilities.fn())["capabilities"][0]["capability"] == (
        Capability.NOTIFY_IT_HELPDESK.value
    )
    refused = await request_capability.fn(Capability.CREATE_CHANGE_REQUEST.value,
                                          {"short_description": "reach across"})
    assert refused["status"] == "denied"
    assert "not in this mission's capability grant" in refused["reason"]

    present(tokens["B"])
    assert (await mcp_gateway.list_capabilities.fn())["capabilities"][0]["capability"] == (
        Capability.CREATE_CHANGE_REQUEST.value
    )
    refused = await request_capability.fn(Capability.NOTIFY_IT_HELPDESK.value, {"summary": "s"})
    assert refused["status"] == "denied"
    assert "not in this mission's capability grant" in refused["reason"]
