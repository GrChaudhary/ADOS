"""
Manual, explicit orphan sweep — removes Docker containers/networks and
workspace directories a terminated runtime session's teardown could not
remove (orchestrate/runtime/orphan_sweep.py).

Deliberately NOT wired into a scheduler, a background task, or ADOS startup:
this phase (P7-C) was explicitly scoped to detection-and-safe-removal, not
resume/heartbeats/scheduling. Run it by hand, or from cron/CI if an operator
chooses to — that choice is out of scope here, this is just the command.

Usage:
    python scripts/sweep_orphans.py
    python scripts/sweep_orphans.py --limit 10
    python scripts/sweep_orphans.py --lease-seconds 60
    python scripts/sweep_orphans.py --all-hosts   # P16: ignore owner_host

P16: by default this only claims sessions this host created (or pre-P16 rows
with no recorded owner) -- the same host-scoping backend/app/main.py's
periodic sweep now uses, and for the same reason: this host's Docker daemon
cannot tell "genuinely gone" apart from "lives on a different host". Pass
--all-hosts to run the old, unscoped behavior (e.g. an operator deliberately
consolidating cleanup from one host that can reach every host's daemon).
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.config import settings
from db.engine import async_session_factory, engine
from orchestrate.runtime.orphan_sweep import (
    CLAIM_LEASE_SECONDS_DEFAULT, DEFAULT_CLAIM_LIMIT, effective_node_id, sweep_once,
)


async def _run(args: argparse.Namespace) -> int:
    node_id = None if args.all_hosts else effective_node_id(settings.node_id)
    report = await sweep_once(
        async_session_factory, limit=args.limit, lease_seconds=args.lease_seconds, node_id=node_id,
    )
    print(f"sweep {report.sweep_id}")
    print(f"  claimed: {report.claimed}")
    print(f"  cleaned: {report.cleaned}")
    print(f"  absent:  {report.absent}")
    print(f"  refused: {report.refused}")
    print(f"  failed:  {report.failed}")
    print(f"  unverifiable: {report.unverifiable}")
    if report.outcomes:
        print()
        for outcome in report.outcomes:
            print(f"  [{outcome.status:8}] {outcome.item.kind:16} {outcome.item.name}  -- {outcome.detail}")

    await engine.dispose()
    return 1 if report.failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=DEFAULT_CLAIM_LIMIT, help="max sessions claimed in this pass")
    parser.add_argument(
        "--lease-seconds", type=float, default=CLAIM_LEASE_SECONDS_DEFAULT,
        help="how long a claim blocks a concurrent sweep before it is considered abandoned",
    )
    parser.add_argument(
        "--all-hosts", action="store_true",
        help="P16: ignore owner_host and claim every eligible session regardless of which host created it",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
