"""
The ONLY way out of a Prime Agent runtime container.

WHY THIS IS A RELAY AND NOT AN HTTP PROXY
-----------------------------------------
An HTTP proxy takes the destination from the client: `CONNECT host:port`. That
makes the client's cooperation part of the security model, and it fails here
twice over.

First, it would not work. Prime Agent talks to OpenAI-compatible providers
through the OpenAI SDK on Node 22, whose fetch does NOT honour HTTP_PROXY /
HTTPS_PROXY — the SDK's own error text says a dispatcher must be passed
explicitly in code. Env-var proxy settings would be silently ignored and every
model call would simply fail, so enforcing policy that way would mean patching
Prime Agent's networking.

Second, and more important: a client-supplied destination is a destination the
client can lie about. Every open-proxy abuse, every redirect escape, every
"connect by IP to dodge the hostname rule" trick exists because the client gets
to name where it is going.

So it does not get to. Each listener here is pinned at start-up to exactly one
upstream `host:port`, taken from configuration ADOS wrote. There is no request
parsing, no CONNECT verb, no URL, no SNI routing, no client-supplied field of
any kind. A connection to port N goes to the one upstream bound to port N or it
goes nowhere. **This cannot be abused as an open proxy because there is no way
to ask it for an arbitrary destination.**

WHAT ACTUALLY ENFORCES THE BOUNDARY
-----------------------------------
Not this process. The container sits on a Docker `--internal` network, which
has **no default route at all** (verified: `ip route | grep -c default` == 0)
and no external DNS. The relay is the only peer it can reach. This process
decides which upstreams exist; the kernel decides that nothing else is
reachable. That ordering matters — a filtering component that can be bypassed
by ignoring it is decoration.

Deliberately NOT here: no TLS termination, no CA injection, no traffic
inspection. TLS runs end to end between the agent and the real upstream, which
keeps certificate validation meaningful. The goal is to constrain *where* the
runtime can talk, not to read what it says.
"""

import asyncio
import json
import os
import sys
from typing import Dict, List, Tuple

# Bytes moved per pipe direction before we stop counting. Purely for the log
# line; there is no cap on what a permitted destination may transfer.
_LOG_EVERY = 1 << 20


def _log(*parts: object) -> None:
    print(*parts, flush=True, file=sys.stderr)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> int:
    moved = 0
    try:
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
            moved += len(chunk)
    except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass
    return moved


def _make_handler(listen_port: int, upstream_host: str, upstream_port: int):
    async def handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter):
        peer = client_writer.get_extra_info("peername")
        try:
            up_reader, up_writer = await asyncio.wait_for(
                asyncio.open_connection(upstream_host, upstream_port), timeout=20.0
            )
        except Exception as exc:
            # The upstream is on the allowlist and still unreachable — a real
            # fault, logged as such. It is NOT a policy denial, and conflating
            # the two would make the policy look like it was doing something it
            # was not.
            _log(f"UPSTREAM-FAIL :{listen_port} -> {upstream_host}:{upstream_port} {type(exc).__name__}: {exc}")
            client_writer.close()
            return

        _log(f"ALLOW {peer} :{listen_port} -> {upstream_host}:{upstream_port}")
        await asyncio.gather(
            _pipe(client_reader, up_writer),
            _pipe(up_reader, client_writer),
            return_exceptions=True,
        )

    return handle


def _parse_allowlist() -> List[Tuple[int, str, int]]:
    """Read the pinned destinations. Refuses anything ambiguous.

    Shape: [{"listen_port": 8077, "host": "host.docker.internal", "port": 8077}]
    """
    raw = os.environ.get("ADOS_RELAY_ALLOW", "").strip()
    if not raw:
        raise SystemExit("ADOS_RELAY_ALLOW is empty — refusing to start a relay with no policy")

    entries = json.loads(raw)
    if not isinstance(entries, list) or not entries:
        raise SystemExit("ADOS_RELAY_ALLOW must be a non-empty list")

    seen: Dict[int, str] = {}
    parsed: List[Tuple[int, str, int]] = []
    for entry in entries:
        listen_port = int(entry["listen_port"])
        host = str(entry["host"])
        port = int(entry["port"])
        if not host or host in ("0.0.0.0", "*"):
            raise SystemExit(f"refusing wildcard upstream host {host!r}")
        if listen_port in seen:
            # Two allowed destinations sharing a listen port cannot be told
            # apart without inspecting client-supplied data (SNI), which is
            # exactly what this design refuses to trust. Fail loudly at start
            # rather than silently sending one host's traffic to the other.
            raise SystemExit(
                f"listen port {listen_port} is claimed by both {seen[listen_port]} and "
                f"{host}:{port} — a relay cannot disambiguate these without trusting the client"
            )
        seen[listen_port] = f"{host}:{port}"
        parsed.append((listen_port, host, port))
    return parsed


async def main() -> None:
    allowlist = _parse_allowlist()
    servers = []
    for listen_port, host, port in allowlist:
        server = await asyncio.start_server(
            _make_handler(listen_port, host, port), "0.0.0.0", listen_port
        )
        servers.append(server)
        _log(f"PINNED :{listen_port} -> {host}:{port}")

    _log(f"READY {len(allowlist)} pinned destination(s); nothing else is reachable")
    await asyncio.gather(*(s.serve_forever() for s in servers))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
