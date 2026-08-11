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
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.engine import async_session_factory, engine
from orchestrate.runtime.orphan_sweep import CLAIM_LEASE_SECONDS_DEFAULT, DEFAULT_CLAIM_LIMIT, sweep_once


async def _run(args: argparse.Namespace) -> int:
    report = await sweep_once(
        async_session_factory, limit=args.limit, lease_seconds=args.lease_seconds,
    )
    print(f"sweep {report.sweep_id}")
    print(f"  claimed: {report.claimed}")
    print(f"  cleaned: {report.cleaned}")
    print(f"  absent:  {report.absent}")
    print(f"  refused: {report.refused}")
    print(f"  failed:  {report.failed}")
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
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
