"""
The runtime's network boundary — an enforced egress allowlist, not a placement.

WHAT THIS REPLACED
------------------
The runtime used to sit on a shared Docker bridge (`ados-runtime-net`) with
`--add-host host.docker.internal:host-gateway`. That is **placement, not
filtering**: the container could reach any host on the internet, because it had
a default route and working DNS. The limitations document said so in as many
words rather than claiming an allowlist that did not exist.

THE TOPOLOGY
------------
Per session, two Docker networks and one extra container:

    ados-rt-<session>          --internal, no default route, no external DNS
      +-- prime agent container      the only peer it can reach is the relay
      +-- egress relay               dual-homed

    ados-rt-out-<session>      ordinary bridge, the relay's way out
      +-- egress relay

The agent container is on the internal network ONLY. A Docker `--internal`
network installs no default route (measured: `ip route | grep -c default` is 0)
and cannot resolve external names, so:

  * arbitrary internet destinations       unreachable — no route
  * the Docker host and its services      unreachable — no route
  * other ADOS containers                 unreachable — different network
  * other missions' runtimes              unreachable — the network is per session
  * DNS-based exfiltration                impossible — no external resolver

The relay is the only thing it can talk to, and the relay's listeners are
pinned to specific upstreams (see the relay's own module docstring). The agent
reaches an allowed destination because ADOS writes a `--add-host` entry
mapping that hostname to the relay's address — not because it can resolve it.

WHY PER-SESSION NETWORKS
------------------------
A shared internal network would let two concurrent missions' runtimes reach
each other, and each other's relay. Container-to-container access between
missions is not a property anyone asked for and would be an odd one to
discover later, so each session gets its own.

WHAT THIS DOES NOT DO
---------------------
It does not give the runtime credentials for anything. The allowlist is the
ADOS MCP gateway and the model provider — nothing else. In particular there is
no direct route to ServiceNow, to Postgres, or to any other downstream system:
those remain reachable only *through* ADOS, behind the session token, the
server-side capability grant, governance, and a connector. Widening the
network boundary must never become a way to skip that chain.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("ados.runtime.egress")

RELAY_IMAGE = "ados-egress-relay:1"

# Hostnames Docker resolves to the host machine. They need the relay's own
# `--add-host ...:host-gateway` to be resolvable *by the relay*, since the
# relay is what actually opens the upstream connection.
_HOST_ALIASES = {"host.docker.internal", "gateway.docker.internal"}

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class Destination:
    """One permitted upstream. Both fields come from ADOS configuration; none
    of it is ever supplied by the runtime."""

    host: str
    port: int

    @property
    def is_host_alias(self) -> bool:
        return self.host in _HOST_ALIASES


def destination_from_url(url: str) -> Optional[Destination]:
    """Extract host:port from a configured endpoint URL.

    Returns None for a URL with no host — a caller passing one has a
    configuration problem, and inventing a destination to paper over it would
    put an unintended host on the allowlist.
    """
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    port = parsed.port or _DEFAULT_PORTS.get((parsed.scheme or "").lower())
    if port is None:
        return None
    return Destination(host=parsed.hostname, port=int(port))


def build_allowlist(*, mcp_url: str, models_json: Optional[Dict] = None,
                    provider: Optional[str] = None) -> List[Destination]:
    """The minimum set of destinations a real session needs.

    Exactly two kinds of thing, and the reasoning for each is short enough to
    audit:

      1. the ADOS MCP gateway — without it the runtime cannot retrieve
         evidence or request a capability, which is the entire point of it;
      2. the configured model endpoint — without it there is no inference.

    Everything else Prime Agent might otherwise want at run time has been
    removed at build time on purpose: the kernel is pinned via
    PRIME_AGENT_KERNEL_PYTHON so it never pip/uv-installs, and
    PRIME_AGENT_TELEMETRY=0. If a session turns out to need something more,
    the relay logs the failure rather than quietly allowing it.
    """
    destinations: List[Destination] = []

    gateway = destination_from_url(mcp_url)
    if gateway is None:
        raise ValueError(f"cannot derive an egress destination from mcp_url={mcp_url!r}")
    destinations.append(gateway)

    for base_url in _provider_base_urls(models_json, provider):
        provider_destination = destination_from_url(base_url)
        if provider_destination is None:
            raise ValueError(f"cannot derive an egress destination from provider baseUrl={base_url!r}")
        if provider_destination not in destinations:
            destinations.append(provider_destination)

    return destinations


def _provider_base_urls(models_json: Optional[Dict], provider: Optional[str]) -> List[str]:
    """Provider endpoints declared in the session's models.json.

    Only the providers actually declared — this does not guess at built-in
    provider URLs. A built-in provider (groq, anthropic, ...) used without a
    models_json entry will have no allowlist entry, the model call will fail,
    and the relay log will name the destination that was refused. That is a
    louder and more honest outcome than shipping a table of vendor URLs that
    drifts.
    """
    if not models_json:
        return []
    providers = (models_json or {}).get("providers") or {}
    urls: List[str] = []
    for name, config in providers.items():
        if provider and name != provider:
            continue
        base_url = (config or {}).get("baseUrl")
        if base_url:
            urls.append(base_url)
    return urls


def relay_policy(destinations: Sequence[Destination]) -> str:
    """The relay's ADOS_RELAY_ALLOW payload.

    The listen port equals the upstream port so a client connecting to
    `host:port` reaches the right listener after the hosts entry redirects the
    name. The relay refuses to start if two destinations collide on a port,
    rather than guessing between them.
    """
    return json.dumps(
        [{"listen_port": d.port, "host": d.host, "port": d.port} for d in destinations]
    )


def host_entries(destinations: Sequence[Destination], relay_ip: str) -> List[str]:
    """`--add-host` arguments pointing every allowed hostname at the relay.

    This is how an allowed name resolves at all: the container has no external
    DNS, so a name absent from this list cannot be turned into an address.
    """
    return [f"{d.host}:{relay_ip}" for d in dict.fromkeys(destinations)]


async def _run(*args: str, timeout: float = 60.0) -> Tuple[int, str]:
    import subprocess

    proc = await asyncio.create_subprocess_exec(
        *args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise TimeoutError(f"timed out: {' '.join(args)}")
    return proc.returncode, out.decode(errors="replace")


async def remove_quietly(kind: str, name: str, *args: str) -> List[str]:
    """One docker removal that cannot raise. Returns [] or a single description
    of what is still there.

    Shared by both teardown paths so "could not remove" means the same thing on
    a relay, a network, and a runtime container. "No such X" counts as removed:
    the goal is absence, and a resource that was never created, or that already
    went away, satisfies it.
    """
    try:
        code, out = await _run(*args, timeout=60.0)
    except Exception as exc:  # noqa: BLE001 — including TimeoutError, see teardown()
        return [f"{kind} {name}: {type(exc).__name__}: {exc}"]
    if code != 0 and "no such" not in out.lower() and "not found" not in out.lower():
        return [f"{kind} {name}: {out.strip()[:200]}"]
    return []


_SAFE_SUFFIX = re.compile(r"[^a-zA-Z0-9_.-]")

# Docker labels attached to every resource this module creates. Existence
# alone was the only ownership evidence before P7-C: a name matching the
# `ados-rt-<suffix>` pattern was trusted to BE this session's network. That is
# a loose prefix, not proof — anything sharing the pattern (a hand-run test
# container, a name collision) would satisfy it too. `LABEL_SESSION` carries
# the exact session_id an orphan sweeper (orchestrate/runtime/orphan_sweep.py)
# can compare against a specific database row, and `LABEL_MANAGED_BY` marks
# the resource as ADOS's own regardless of what created it. Neither label is
# read by anything at request time; this boundary's own behaviour is
# unchanged. They exist purely as after-the-fact ownership evidence.
LABEL_SESSION = "ados.session_id"
LABEL_MANAGED_BY = "ados.managed_by"
LABEL_MANAGED_BY_VALUE = "ados-prime-agent"
LABEL_COMPONENT = "ados.component"


def _is_ip_literal(host: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class EgressBoundary:
    """Creates, and tears down, one session's enforced network boundary."""

    def __init__(self, session_id: str, destinations: Sequence[Destination]):
        if not destinations:
            # A boundary with nothing allowed would leave the runtime unable to
            # reach ADOS at all. That is a configuration error, not a stricter
            # policy, and it should be visible immediately.
            raise ValueError("refusing to build an egress boundary with an empty allowlist")

        # An allowed destination reaches the relay because `--add-host` maps its
        # NAME to the relay's address. /etc/hosts maps names, not addresses, so
        # an IP-literal destination gets no redirect: the runtime connects to it
        # directly, finds no route, and the destination is unreachable despite
        # being "allowed". Refuse it here rather than hand back a boundary whose
        # allowlist quietly does not work — this was found by a test fixture
        # that pinned an IP and then could not reach its own permitted upstream.
        literals = [d.host for d in destinations if _is_ip_literal(d.host)]
        if literals:
            raise ValueError(
                f"egress destinations must be hostnames, not IP literals: {literals}. "
                "The allowlist works by redirecting a NAME to the relay, so an "
                "address-literal endpoint cannot be permitted this way."
            )
        suffix = _SAFE_SUFFIX.sub("", session_id)[:24]
        self.session_id = session_id
        self.destinations = list(destinations)
        self.internal_network = f"ados-rt-{suffix}"
        self.egress_network = f"ados-rt-out-{suffix}"
        self.relay_container = f"ados-relay-{suffix}"
        self.relay_ip: Optional[str] = None

    def _label_args(self, component: str) -> List[str]:
        return [
            "--label", f"{LABEL_SESSION}={self.session_id}",
            "--label", f"{LABEL_MANAGED_BY}={LABEL_MANAGED_BY_VALUE}",
            "--label", f"{LABEL_COMPONENT}={component}",
        ]

    async def start(self) -> None:
        await _run(
            "docker", "network", "create", "--internal",
            *self._label_args("network_internal"), self.internal_network, timeout=30.0,
        )
        await _run(
            "docker", "network", "create",
            *self._label_args("network_egress"), self.egress_network, timeout=30.0,
        )

        args = [
            "docker", "run", "-d",
            "--name", self.relay_container,
            "--network", self.internal_network,
            *self._label_args("relay"),
            # The relay resolves and reaches upstreams itself, so IT needs the
            # host mapping — the agent container never gets one.
            "--add-host", "host.docker.internal:host-gateway",
            "-e", f"ADOS_RELAY_ALLOW={relay_policy(self.destinations)}",
            "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
            RELAY_IMAGE,
        ]
        code, out = await _run(*args, timeout=120.0)
        if code != 0:
            await self.teardown()
            raise RuntimeError(f"egress relay failed to start: {out[-2000:]}")

        # Second leg: the relay's own route out. Attached after creation so the
        # agent's internal network stays the relay's primary interface.
        code, out = await _run(
            "docker", "network", "connect", self.egress_network, self.relay_container, timeout=30.0
        )
        if code != 0:
            await self.teardown()
            raise RuntimeError(f"could not attach the relay to its egress network: {out[-500:]}")

        code, out = await _run(
            "docker", "inspect", "-f",
            "{{(index .NetworkSettings.Networks \"" + self.internal_network + "\").IPAddress}}",
            self.relay_container, timeout=30.0,
        )
        self.relay_ip = out.strip()
        if code != 0 or not self.relay_ip:
            await self.teardown()
            raise RuntimeError(f"could not determine the relay's address on the internal network: {out[-500:]}")

        await self._await_ready()

        logger.info(
            "Egress boundary up",
            extra={
                "network": self.internal_network,
                "relay": self.relay_container,
                "allow": [f"{d.host}:{d.port}" for d in self.destinations],
            },
        )

    async def _await_ready(self, timeout: float = 30.0) -> None:
        """Block until every pinned port is actually accepting connections.

        Measured, not assumed: `docker run -d` returns as soon as the container
        is created, and the relay's listeners came up roughly a second later.
        Starting the agent in that window gives it a boundary that blocks
        everything — including ADOS — so the first capability call fails for a
        reason that has nothing to do with policy and does not reproduce.

        Worth stating plainly because it nearly shipped: a blocked-everything
        relay passes every test that only asserts things are unreachable. The
        readiness check and the reachability assertion in
        `test_runtime_egress_boundary.py` exist as a pair for that reason.

        The probe runs inside the relay against 127.0.0.1, so it tests the
        listener itself rather than the network path to it.
        """
        ports = sorted({d.port for d in self.destinations})
        script = (
            "import socket,sys\n"
            f"for p in {ports!r}:\n"
            "    s=socket.socket()\n"
            "    s.settimeout(2)\n"
            "    try:\n"
            "        s.connect(('127.0.0.1',p))\n"
            "    except Exception:\n"
            "        sys.exit(1)\n"
            "    finally:\n"
            "        s.close()\n"
            "print('READY')\n"
        )
        deadline = asyncio.get_event_loop().time() + timeout
        last = ""
        while asyncio.get_event_loop().time() < deadline:
            code, out = await _run(
                "docker", "exec", self.relay_container, "python3", "-c", script, timeout=15.0
            )
            if code == 0 and "READY" in out:
                return
            last = out
            await asyncio.sleep(0.5)

        await self.teardown()
        raise RuntimeError(
            f"egress relay never began listening on {ports} within {timeout}s: {last[-300:]}"
        )

    def container_args(self) -> List[str]:
        """Docker arguments placing a runtime container inside this boundary.

        Note what is absent: no `--add-host host.docker.internal:host-gateway`.
        That entry is what used to give the runtime a path to the host, and it
        is deliberately not reissued here — `host.docker.internal` resolves to
        the relay if and only if it is an allowed destination.
        """
        assert self.relay_ip, "start() first"
        args = ["--network", self.internal_network, *self._label_args("prime_container")]
        for entry in host_entries(self.destinations, self.relay_ip):
            args += ["--add-host", entry]
        return args

    async def relay_log(self) -> str:
        code, out = await _run("docker", "logs", self.relay_container, timeout=20.0)
        return out if code == 0 else ""

    async def teardown(self) -> List[str]:
        """Never raises, and reports what survived.

        Failures are collected, not raised: teardown runs in a `finally` and
        must not mask the real outcome. `_run` raises `TimeoutError` on a
        wedged daemon, so the relay removal is guarded too — without that, a
        hung `docker rm` would skip both networks and leave a per-session
        network attached to nothing, which is exactly the orphan shape found
        after the P6-B daemon crash.
        """
        leftovers: List[str] = []
        leftovers += await remove_quietly(
            "relay", self.relay_container, "docker", "rm", "-f", self.relay_container
        )
        # Networks only disappear once nothing is attached, so container
        # removal has to come first.
        for network in (self.internal_network, self.egress_network):
            leftovers += await remove_quietly(
                "network", network, "docker", "network", "rm", network
            )
        for note in leftovers:
            logger.warning("egress teardown left a resource behind: %s", note)
        return leftovers
