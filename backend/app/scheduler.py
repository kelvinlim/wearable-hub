"""Consolidation scheduler — runs as the `scheduler` compose service (`python -m app.scheduler`).

Jobs (all defensive — a failure is logged, never crashes the scheduler):
  - **nightly** (cron, `CONSOLIDATION_NIGHTLY_HOUR`, container TZ=UTC): the safety-net —
    re-mark the last few local days dirty for every registered subject and drain them, so any
    day missed by the real-time webhook path self-heals.
  - **drain** (interval, `CONSOLIDATION_DRAIN_INTERVAL_MINUTES`): drain the durable
    `consolidation_state` queue promptly, so a missed/crashed real-time BackgroundTask is
    recovered within minutes rather than waiting for the nightly run. Set the interval to 0
    to disable.
  - **oura_renew** (daily cron, only when OURA_CLIENT_ID is set): Oura's app-level webhook
    subscriptions expire; renew any within OURA_WEBHOOK_RENEW_DAYS_BEFORE of expiry.

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


def _oura_renew_job() -> None:
    from datetime import datetime, timedelta, timezone

    from app.providers import oura

    s = get_settings()
    try:
        subs = oura.list_webhook_subscriptions()
        horizon = datetime.now(timezone.utc) + timedelta(days=s.oura_webhook_renew_days_before)
        renewed = 0
        for sub in subs:
            exp_raw = str(sub.get("expiration_time") or "")
            try:
                exp = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if exp <= horizon:
                oura.renew_webhook_subscription(str(sub.get("id")))
                renewed += 1
        log.info("oura webhook renew: %s/%s renewed", renewed, len(subs))
    except Exception:  # noqa: BLE001 — keep the scheduler alive
        log.exception("oura webhook renew failed")


def main() -> None:
    s = get_settings()
    sched = BlockingScheduler()
    sched.add_job(_nightly_job, "cron", hour=s.consolidation_nightly_hour, id="nightly")
    if s.consolidation_drain_interval_minutes > 0:
        sched.add_job(
            _drain_job, "interval", minutes=s.consolidation_drain_interval_minutes, id="drain"
        )
    if s.oura_client_id:
        sched.add_job(
            _oura_renew_job, "cron", hour=s.consolidation_nightly_hour, minute=30, id="oura_renew"
        )
    log.info(
        "scheduler starting: nightly@%02d:00 UTC, drain every %s min, oura renew %s",
        s.consolidation_nightly_hour,
        s.consolidation_drain_interval_minutes or "off",
        "on" if s.oura_client_id else "off",
    )
    sched.start()


if __name__ == "__main__":
    main()
