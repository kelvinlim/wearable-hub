"""Consolidation scheduler — runs as the `scheduler` compose service (`python -m app.scheduler`).

Two jobs (both defensive — a failure is logged, never crashes the scheduler):
  - **nightly** (cron, `CONSOLIDATION_NIGHTLY_HOUR`, container TZ=UTC): the safety-net —
    re-mark the last few local days dirty for every registered subject and drain them, so any
    day missed by the real-time webhook path self-heals.
  - **drain** (interval, `CONSOLIDATION_DRAIN_INTERVAL_MINUTES`): drain the durable
    `consolidation_state` queue promptly, so a missed/crashed real-time BackgroundTask is
    recovered within minutes rather than waiting for the nightly run. Set the interval to 0
    to disable.

The real-time path (webhook → BackgroundTasks) remains the primary, freshest mechanism; this
service is purely the durable backstop.
"""

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.config import get_settings
from app.db import SessionLocal
from app import consolidation
from app.jobs import nightly

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("scheduler")


def _nightly_job() -> None:
    try:
        log.info("nightly consolidation: %s", nightly.run())
    except Exception:  # noqa: BLE001 — keep the scheduler alive
        log.exception("nightly consolidation failed")


def _drain_job() -> None:
    db = SessionLocal()
    try:
        result = consolidation.consolidate_due(db)
        if result["done"] or result["errors"]:
            log.info("drain: %s", result)
    except Exception:  # noqa: BLE001 — keep the scheduler alive (e.g. DB not ready yet)
        log.exception("drain failed")
    finally:
        db.close()


def main() -> None:
    s = get_settings()
    sched = BlockingScheduler()
    sched.add_job(_nightly_job, "cron", hour=s.consolidation_nightly_hour, id="nightly")
    if s.consolidation_drain_interval_minutes > 0:
        sched.add_job(
            _drain_job, "interval", minutes=s.consolidation_drain_interval_minutes, id="drain"
        )
    log.info(
        "scheduler starting: nightly@%02d:00 UTC, drain every %s min",
        s.consolidation_nightly_hour,
        s.consolidation_drain_interval_minutes or "off",
    )
    sched.start()


if __name__ == "__main__":
    main()
