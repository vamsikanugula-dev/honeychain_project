"""Reconcile pending, submitted or failed Fabric outbox events.

Run from cron, a deployment scheduler or an operator terminal::

    python -m app.scripts.blockchain_outbox_worker --limit 100

It uses the same persistent database rows and centralized client as the API; it
never creates an operational entity or accepts a transaction from stdin.
"""

from __future__ import annotations

import argparse

from app.core.database import SessionLocal
from app.services.blockchain_service import BlockchainService


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry HoneyChain blockchain outbox events")
    parser.add_argument("--limit", type=int, default=100, help="Maximum pending/failed events to process")
    args = parser.parse_args()
    with SessionLocal() as session:
        remaining = BlockchainService(session).retry_pending(limit=max(1, min(args.limit, 500)))
        print(f"Blockchain retry complete; {len(remaining)} event(s) remain retryable.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
