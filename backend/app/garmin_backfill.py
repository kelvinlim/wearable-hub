"""Trigger Garmin historical backfill (re-push) for a provider account.

Garmin has **no pull API** — instead you ask it to re-push historical summaries to the registered
webhooks via `GET /backfill/{summaryType}`. The per-request window is capped (~90 days in practice),
so a long range is chunked. Each (type, window) request is **async**: Garmin returns 202 and the data
arrives later through the normal `/webhooks/garmin/{type}` path, where `app/garmin_ingest.py`
aggregates it (idempotent, so re-pushed days self-heal).

Only summary types whose webhook is registered/enabled in the Garmin portal will actually deliver —
a backfill for a disabled type is accepted but the re-pushed data is dropped on Garmin's side.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt
from app.models import ProviderAccount
from app.providers import garmin

log = logging.getLogger(__name__)


def _epoch(d: date) -> int:
    """UTC midnight of `d` as epoch seconds (Garmin backfill bounds are UTC epoch seconds)."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _windows(start: date, end: date, max_days: int):
    """Yield (chunk_start, chunk_end) inclusive date windows, each spanning <= max_days days."""
    step = max(1, max_days)
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=step - 1), end)
        yield cur, chunk_end
        cur = chunk_end + timedelta(days=1)


def configured_types() -> list[str]:
    """Default backfill summary types (from settings; comma-separated)."""
    raw = get_settings().garmin_backfill_types or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


def backfill_account(
    db: Session,
    account: ProviderAccount,
    start: date,
    end: date,
    *,
    types: list[str] | None = None,
) -> list[dict]:
    """Fire Garmin backfill requests for `account` over [start, end] inclusive.

    Loops the configured summary types × chunked windows. Never raises on a single failed request
    (one bad type/window shouldn't drop the rest); each result row records the HTTP status or error.
    `db` is unused today (the work is all outbound) but kept for parity with the other ingest
    entry points and a future audit-log write.
    """
    settings = get_settings()
    uat = decrypt(account.access_token)
    secret = decrypt(account.refresh_token)
    if not uat or not secret:
        raise ValueError("Garmin account has no stored access token/secret")
    use_types = types if types is not None else configured_types()
    max_days = settings.garmin_backfill_max_window_days
    results: list[dict] = []
    for summary_type in use_types:
        for cstart, cend in _windows(start, end, max_days):
            row = {"type": summary_type, "start": cstart.isoformat(), "end": cend.isoformat()}
            try:
                # End bound is exclusive: midnight of the day after `cend`.
                row["status"] = garmin.request_backfill(
                    uat, secret, summary_type, _epoch(cstart), _epoch(cend + timedelta(days=1))
                )
            except Exception as exc:  # noqa: BLE001 — record + continue
                log.exception(
                    "Garmin backfill %s %s..%s failed for account %s",
                    summary_type, cstart, cend, account.id,
                )
                row["error"] = str(exc)
            results.append(row)
    return results
