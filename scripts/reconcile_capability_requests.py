"""
Manual, explicit reconciliation for `capability_requests` rows a crash or an
ambiguous external response left without a known outcome
(orchestrate/runtime/capability_reconcile.py).

Two passes, run in order (the second only ever has work because of the
first, or because a connector returned `CallStatus.UNKNOWN` directly):

  1. mark-stalled — rows stuck at `executing` past the stall bound become
     `outcome_unknown`. Never guesses success or failure.
  2. reconcile     — rows at `outcome_unknown` are checked against the real
     external system by canonical `request_id`. A match resolves the row to
     `executed` and creates nothing new; no match leaves it exactly where it
     was.

Deliberately NOT wired into a scheduler, matching `scripts/sweep_orphans.py`'s
own precedent: the correctness guarantee (a row can never be silently
re-executed) does not depend on this script ever running. Run it by hand, or
from cron/CI if an operator chooses to — that choice is out of scope here.

Usage:
    python scripts/reconcile_capability_requests.py
    python scripts/reconcile_capability_requests.py --stall-seconds 30
    python scripts/reconcile_capability_requests.py --limit 10
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.engine import async_session_factory, engine
from orchestrate.runtime.capability_execution import EXECUTION_STALL_SECONDS_DEFAULT
from orchestrate.runtime.capability_reconcile import (
    DEFAULT_RECONCILE_LIMIT,
    mark_stalled_executions_unknown,
    reconcile_outcome_unknown,
)


async def _run(args: argparse.Namespace) -> int:
    stalled = await mark_stalled_executions_unknown(
        async_session_factory, stall_seconds=args.stall_seconds, limit=args.limit,
    )
    print(f"mark-stalled: {len(stalled)} row(s) moved executing -> outcome_unknown")
    for item in stalled:
        print(f"  [outcome_unknown] request {item.request_id}  executing since {item.executing_since}")

    outcomes = await reconcile_outcome_unknown(async_session_factory, limit=args.limit)
    resolved = [o for o in outcomes if o.resolved]
    print(f"reconcile: {len(outcomes)} row(s) checked, {len(resolved)} resolved")
    for outcome in outcomes:
        tag = "executed" if outcome.resolved else "outcome_unknown"
        print(f"  [{tag:14}] request {outcome.request_id}  -- {outcome.detail}")

    await engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--stall-seconds", type=float, default=EXECUTION_STALL_SECONDS_DEFAULT,
        help="how long a row may sit at 'executing' before it is presumed abandoned",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_RECONCILE_LIMIT, help="max rows processed per pass")
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
