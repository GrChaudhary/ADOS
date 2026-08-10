"""
The runtime's network boundary, proved from INSIDE the real container.

Configuration is not a boundary. `--network some-net` in a docker run line is a
claim; what matters is what a process inside that container can actually open a
socket to. So the `docker` tests here start the real `ados-prime-runtime` image
inside a real `EgressBoundary` and try to reach things from within it, using the
Python that the agent's own kernel runs.

These are marked `docker` and DESELECTED by default, alongside `external`:
they build networks and containers, take ~30s, and a laptop running `pytest`
should not need Docker. Run them deliberately:

    pytest -m docker backend/tests/test_runtime_egress_boundary.py

The pure-policy tests above them need nothing and run in the normal suite.

WHAT IS PROVEN HERE VS ASSERTED ELSEWHERE
-----------------------------------------
Proven from inside the container: no default route, no external DNS, arbitrary
internet destinations unreachable, the Docker host unreachable, an allowed
destination reachable, a disallowed port on an allowed host unreachable, and
that the relay cannot be asked for a destination of the caller's choosing.

Not proven here: that a full mission still completes through the boundary. That
needs a live model and is a separate, explicitly invoked run.
"""

import json
import shutil
import subprocess
import uuid

import pytest

from orchestrate.runtime.egress import (
    Destination,
    EgressBoundary,
    build_allowlist,
    destination_from_url,
    host_entries,
    relay_policy,
)

RUNTIME_IMAGE = "ados-prime-runtime:0.7.1"
RELAY_IMAGE = "ados-egress-relay:1"

MODELS_JSON = {
    "providers": {
        "ollama-local": {
            "baseUrl": "http://host.docker.internal:11434/v1",
            "api": "openai-completions",
            "models": [{"id": "qwen3-4b-16k:latest"}],
        }
    }
}


# --- policy (no Docker needed) -----------------------------------------------

def test_the_allowlist_is_the_gateway_and_the_model_endpoint_and_nothing_else():
    allow = build_allowlist(
        mcp_url="http://host.docker.internal:8077/mcp/",
        models_json=MODELS_JSON,
        provider="ollama-local",
    )
    assert allow == [
        Destination("host.docker.internal", 8077),
        Destination("host.docker.internal", 11434),
    ]


def test_a_provider_that_is_not_this_sessions_provider_is_not_allowed():
    """Two providers declared, one selected. Only the selected one's endpoint
    belongs on the allowlist — shipping both would widen the boundary to a
    vendor this session never calls."""
    two = {
        "providers": {
            "ollama-local": {"baseUrl": "http://host.docker.internal:11434/v1"},
            "nvidia": {"baseUrl": "https://integrate.api.nvidia.com/v1"},
        }
    }
    allow = build_allowlist(
        mcp_url="http://host.docker.internal:8077/mcp/", models_json=two, provider="ollama-local"
    )
    assert Destination("integrate.api.nvidia.com", 443) not in allow


def test_https_and_http_default_ports_are_derived_not_guessed():
    assert destination_from_url("https://api.groq.com/openai/v1") == Destination("api.groq.com", 443)
    assert destination_from_url("http://example.internal/v1") == Destination("example.internal", 80)
    assert destination_from_url("https://api.groq.com:8443/v1") == Destination("api.groq.com", 8443)


def test_a_url_with_no_host_is_refused_rather_than_invented():
    assert destination_from_url("not-a-url") is None
    with pytest.raises(ValueError):
        build_allowlist(mcp_url="not-a-url")


def test_an_empty_allowlist_is_refused():
    """A boundary allowing nothing would leave the runtime unable to reach
    ADOS. That is a misconfiguration, not a stricter policy."""
    with pytest.raises(ValueError):
        EgressBoundary("s1", [])


def test_an_ip_literal_destination_is_refused_rather_than_silently_unreachable():
    """The allowlist works by redirecting a NAME to the relay via /etc/hosts,
    which cannot redirect an address. An IP-literal endpoint would be accepted
    into the policy and then be unreachable anyway — an allowlist entry that
    does nothing is worse than a rejected configuration, because it looks like
    it works. Found by a fixture that pinned an IP and could not reach its own
    permitted upstream."""
    with pytest.raises(ValueError, match="hostnames, not IP literals"):
        EgressBoundary("s1", [Destination("10.0.0.5", 8077)])
    with pytest.raises(ValueError, match="hostnames, not IP literals"):
        EgressBoundary("s1", [Destination("::1", 8077)])


def test_the_relay_policy_carries_no_wildcards():
    policy = json.loads(relay_policy([Destination("host.docker.internal", 8077)]))
    assert policy == [{"listen_port": 8077, "host": "host.docker.internal", "port": 8077}]
    assert "0.0.0.0" not in json.dumps(policy)
    assert "*" not in json.dumps(policy)


def test_every_allowed_hostname_points_at_the_relay_and_nothing_points_at_the_host():
    entries = host_entries(
        [Destination("host.docker.internal", 8077), Destination("api.groq.com", 443)], "172.30.0.2"
    )
    assert entries == ["host.docker.internal:172.30.0.2", "api.groq.com:172.30.0.2"]
    assert not any("host-gateway" in e for e in entries), (
        "a host-gateway entry would restore the runtime's direct path to the host"
    )


def test_the_runtime_no_longer_asks_for_a_host_gateway_entry():
    """Structural guard on the thing that used to grant host access. If it comes
    back into the runtime's own container arguments, the boundary is silently
    undone while every other test still passes.

    AST, not a text search: the first version of this test grepped the source
    and flagged the *comment* in `start()` explaining that the entry was
    removed. Comments do not appear in an AST, so parsing asks the question
    actually intended — does this function contain that string as code — which
    is the same reason `test_execution_semantics.py` parses rather than greps.
    """
    import ast
    import inspect

    from orchestrate.runtime import prime

    tree = ast.parse(inspect.getsource(prime))
    start = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "start"
    )
    literals = [
        node.value for node in ast.walk(start)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    offenders = [s for s in literals if "host-gateway" in s]
    assert not offenders, (
        f"the runtime container must not receive a host-gateway mapping ({offenders}); "
        "only the relay may reach the host"
    )


# --- the actual boundary (needs Docker) --------------------------------------

pytestmark_docker = pytest.mark.docker


def _images_present() -> bool:
    if not shutil.which("docker"):
        return False
    out = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True, text=True,
    ).stdout
    return RUNTIME_IMAGE in out and RELAY_IMAGE in out


def _exec(container: str, script: str, *argv: str) -> str:
    """Run a probe inside the container using the kernel's own Python."""
    return subprocess.run(
        ["docker", "exec", container, "/home/prime/kernel-venv/bin/python", "-c", script, *argv],
        capture_output=True, text=True, timeout=90,
    ).stdout.strip()


PROBE = r"""
import socket, sys, urllib.request
ALLOWED = sys.argv[1] if len(sys.argv) > 1 else ""
def reach(host, port, timeout=4):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return "REACHABLE"
    except Exception as e:
        return f"BLOCKED({type(e).__name__})"
def resolves(name):
    try:
        return socket.gethostbyname(name)
    except Exception as e:
        return f"NO-RESOLVE({type(e).__name__})"
print("ROUTE_COUNT", open("/proc/net/route").read().count("\n") - 1)
print("DNS_EXTERNAL", resolves("example.com"))
print("DNS_ALLOWED", resolves(ALLOWED))
print("IP_DIRECT_1111", reach("1.1.1.1", 443))
print("IP_DIRECT_8888", reach("8.8.8.8", 53))
print("ALLOWED_DESTINATION", reach(ALLOWED, 8077))
print("DISALLOWED_PORT_ON_ALLOWED_HOST", reach(ALLOWED, 5432))
print("DISALLOWED_PORT_22", reach(ALLOWED, 22))
try:
    r = urllib.request.urlopen(f"http://{ALLOWED}:8077/", timeout=8)
    print("ALLOWED_HTTP", r.status)
except Exception as e:
    print("ALLOWED_HTTP", type(e).__name__)
"""


@pytest.fixture
def boundary():
    """A real runtime container inside a real boundary, plus one disposable
    destination that IS on the allowlist.

    The permitted destination is part of the fixture on purpose. An earlier
    version allowed `host.docker.internal:8077` and asserted only that things
    were unreachable — which a relay that never started listening also
    satisfies, and one did: `docker run -d` returns about a second before the
    listeners come up. A boundary that blocks everything is not the boundary
    anyone wanted, and a blocks-only test cannot tell the difference.
    """
    if not _images_present():
        pytest.skip(f"needs {RUNTIME_IMAGE} and {RELAY_IMAGE} built locally")

    import asyncio

    session = uuid.uuid4().hex[:12]
    container = f"ados-egress-test-{session}"
    listener = f"ados-egress-listener-{session}"
    scratch_net = f"ados-egress-up-{session}"
    b = None
    loop = asyncio.new_event_loop()
    try:
        # A stand-in for the ADOS gateway, on its own network so the relay can
        # reach it the way it reaches the real host.
        subprocess.run(["docker", "network", "create", scratch_net],
                       capture_output=True, timeout=60)
        subprocess.run(
            ["docker", "run", "-d", "--name", listener, "--network", scratch_net,
             "python:3.12-alpine", "python3", "-m", "http.server", "8077"],
            capture_output=True, text=True, check=True, timeout=180,
        )
        # The allowed destination is the listener's CONTAINER NAME, not its IP.
        # That mirrors the real topology exactly: the agent's hosts entry maps
        # the name to the relay, and the relay resolves the same name via
        # Docker's embedded DNS on the network they share. An IP literal cannot
        # work here — /etc/hosts redirects names — and EgressBoundary now
        # refuses one rather than producing an allowlist that does not.
        b = EgressBoundary(session, [Destination(listener, 8077)])
        loop.run_until_complete(b.start())
        # Give the relay a route to the stand-in upstream.
        subprocess.run(["docker", "network", "connect", scratch_net, b.relay_container],
                       capture_output=True, timeout=60)

        subprocess.run(
            ["docker", "run", "-d", "--name", container, *b.container_args(),
             "--memory", "512m", "--pids-limit", "128", RUNTIME_IMAGE, "sleep", "300"],
            capture_output=True, text=True, check=True, timeout=180,
        )
        yield b, container, listener
    finally:
        for name in (container, listener):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=90)
        if b is not None:
            loop.run_until_complete(b.teardown())
        subprocess.run(["docker", "network", "rm", scratch_net], capture_output=True, timeout=60)
        loop.close()


@pytest.mark.docker
def test_the_boundary_permits_exactly_the_allowlist_and_nothing_else(boundary):
    """Both directions in one test, deliberately.

    The blocked assertions alone are satisfied by a container with no network
    at all — and by a relay that never finished starting, which is exactly the
    bug this pairing caught. ALLOWED_HTTP is what makes the rest mean
    something.
    """
    _, container, allowed_ip = boundary
    result = dict(
        line.split(" ", 1)
        for line in _exec(container, PROBE, allowed_ip).splitlines()
        if " " in line
    )

    # THE POSITIVE CONTROL — the boundary permits what it is supposed to.
    assert result["ALLOWED_DESTINATION"] == "REACHABLE", result
    assert result["ALLOWED_HTTP"] == "200", (
        f"the allowed destination did not serve traffic through the relay: {result}"
    )

    # 1. No default route. This, not the relay, is what makes the boundary real.
    assert result["ROUTE_COUNT"] == "1", f"expected only the on-link route, got {result}"

    # 2. External DNS is dead, so names cannot be turned into addresses and DNS
    #    cannot be used as an exfiltration channel.
    assert result["DNS_EXTERNAL"].startswith("NO-RESOLVE"), result["DNS_EXTERNAL"]

    # 3. Arbitrary internet destinations, by IP, bypassing DNS entirely.
    assert result["IP_DIRECT_1111"].startswith("BLOCKED"), result["IP_DIRECT_1111"]
    assert result["IP_DIRECT_8888"].startswith("BLOCKED"), result["IP_DIRECT_8888"]

    # 4. A port on an allowed HOST that is not an allowed DESTINATION. The unit
    #    of policy is host:port, not host — Postgres on the same machine as the
    #    gateway must stay unreachable even though the gateway is allowed.
    assert result["DISALLOWED_PORT_ON_ALLOWED_HOST"].startswith("BLOCKED"), result
    assert result["DISALLOWED_PORT_22"].startswith("BLOCKED"), result


@pytest.mark.docker
def test_the_docker_host_is_unreachable_even_by_name(boundary):
    """`host.docker.internal` was the runtime's path to the host and to every
    port published on it. With no hosts entry and no external DNS the name does
    not resolve at all."""
    _, container, _ = boundary
    got = _exec(container, r"""
import socket
try:
    print("RESOLVED", socket.gethostbyname("host.docker.internal"))
except Exception as e:
    print("NO-RESOLVE", type(e).__name__)
""")
    assert got.startswith("NO-RESOLVE"), f"the host is still nameable from the runtime: {got}"


@pytest.mark.docker
def test_the_relay_cannot_be_asked_for_a_destination_of_the_callers_choosing(boundary):
    """An HTTP proxy takes the destination from the client, which is what makes
    open-proxy abuse and redirect escapes possible. This relay has no such
    field: a CONNECT is just bytes forwarded to the one pinned upstream, so the
    request cannot select a destination even in principle."""
    _, container, allowed_ip = boundary
    got = _exec(container, r"""
import socket, sys
try:
    s = socket.create_connection((sys.argv[1], 8077), timeout=4)
    s.sendall(b"CONNECT evil.example.com:443 HTTP/1.1\r\nHost: evil.example.com\r\n\r\n")
    s.settimeout(4)
    try:
        data = s.recv(128)
    except Exception:
        data = b""
    s.close()
    print("RESPONSE", data[:60])
except Exception as e:
    print("RESPONSE connect-failed", type(e).__name__)
""", allowed_ip)
    # Whatever comes back, it must not be a proxy agreeing to the tunnel.
    assert "200 Connection established" not in got, (
        f"the relay behaved like an open proxy: {got}"
    )
