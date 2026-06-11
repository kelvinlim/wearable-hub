"""Scheduled safety-net: recompute recent days for all registered subjects.

The real-time webhook path is best-effort (a dropped notification or a transient pull failure
can leave a day stale). This re-marks the last few local days dirty for every registered fitbit
account and drains the queue, so steady-state data self-heals.

Run from cron (no in-repo scheduler), e.g. nightly:
    0 4 * * *  cd /app && python -m app.jobs.nightly

Or trigger via the `/schedule` routine / `POST /admin/consolidate/run-due`.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select

from app import consolidation
from app.db import SessionLocal
from app.models import ProviderAccount
from app.providers import fitbit_gh

log = logging.getLogger(__name__)


def run(days_back: int = 2) -> dict:
    """Mark the last `days_back` days (+ today) dirty for all registered accounts, then drain."""
    db = SessionLocal()
    try:
        today = date.today()
        targets = [today - timedelta(days=i) for i in range(days_back + 1)]
        accounts = list(
            db.scalars(
                select(ProviderAccount).where(
                    ProviderAccount.provider == fitbit_gh.NAME,
                    ProviderAccount.registered.is_(True),
                )
            )
        )
        for acct in accounts:
            consolidation.mark_dirty(db, acct.id, targets)
        result = consolidation.consolidate_due(db, limit=100_000)
        log.info("nightly consolidation: accounts=%s %s", len(accounts), result)
        return {"accounts": len(accounts), "days_each": len(targets), **result}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
