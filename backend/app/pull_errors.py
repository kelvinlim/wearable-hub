"""Safe, correlatable errors for on-demand pull / consolidation.

Uncaught exceptions in `POST /admin/subjects/{id}/consolidate` previously became
FastAPI's generic "Internal Server Error" with no failed date and no log correlation.
This module classifies known failure classes into a JSON `detail` the UI can render,
and always attaches a short `error_id` that is also written next to the full traceback
in server logs.

Never put tokens, Authorization headers, upstream response bodies, PHI, SQL, or
stack traces in the API payload. `str(exc)` is log-only.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

REASON_PROVIDER_TIMEOUT = "provider_timeout"
REASON_PROVIDER_UNREACHABLE = "provider_unreachable"
REASON_PROVIDER_HTTP = "provider_http"
REASON_TOKEN_REFRESH = "token_refresh"
REASON_DATABASE = "database"
REASON_UNEXPECTED = "unexpected"

GUIDANCE = {
    REASON_PROVIDER_TIMEOUT: "Retry this date. If it keeps timing out, try a smaller range.",
    REASON_PROVIDER_UNREACHABLE: "The provider could not be reached. Retry shortly.",
    REASON_PROVIDER_HTTP: (
        "The provider rejected or failed a request. Retry this date; re-link the device "
        "if authorization errors persist."
    ),
    REASON_TOKEN_REFRESH: (
        "Could not refresh the device authorization. Re-link the device if this continues."
    ),
    REASON_DATABASE: (
        "A database error stopped the save. Retry this date. If it repeats, share the ref "
        "with an administrator."
    ),
    REASON_UNEXPECTED: "Retry this date. If it repeats, share the ref with an administrator.",
}

_TOKEN_HOST_MARKERS = (
    "oauth2.googleapis.com/token",
    "api.ouraring.com/oauth",
)


def new_error_id() -> str:
    """8 hex chars — unique enough to grep logs, not a secret."""
    return secrets.token_hex(4)


def unexpected_detail(error_id: str) -> dict:
    """Generic 500 body for unhandled exceptions outside the pull loop."""
    return {
        "message": "An unexpected error occurred.",
        "reason": REASON_UNEXPECTED,
        "guidance": "Retry. If it persists, share the ref with an administrator.",
        "error_id": error_id,
    }


def classify_exception(exc: BaseException) -> tuple[str, int, str]:
    """Return `(reason, http_status, safe_message)`. Never interpolates `exc` text."""
    if isinstance(exc, httpx.TimeoutException):
        return (
            REASON_PROVIDER_TIMEOUT,
            504,
            "The wearable provider did not respond in time.",
        )
    if isinstance(exc, httpx.ConnectError):
        return (
            REASON_PROVIDER_UNREACHABLE,
            502,
            "Could not reach the wearable provider.",
        )
    if isinstance(exc, httpx.RequestError):
        return (
            REASON_PROVIDER_UNREACHABLE,
            502,
            "Could not complete the request to the wearable provider.",
        )
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code if exc.response is not None else 0
        if _is_token_url(exc):
            return (
                REASON_TOKEN_REFRESH,
                502,
                f"Could not refresh device authorization (HTTP {code}).",
            )
        if code == 429:
            return (
                REASON_PROVIDER_HTTP,
                429,
                "The wearable provider rate-limited the pull (HTTP 429).",
            )
        if code in (401, 403):
            return (
                REASON_TOKEN_REFRESH,
                502,
                f"The wearable provider returned HTTP {code} (authorization).",
            )
        if 500 <= code <= 599:
            return (
                REASON_PROVIDER_HTTP,
                502,
                f"The wearable provider returned HTTP {code}.",
            )
        return (
            REASON_PROVIDER_HTTP,
            502,
            f"The wearable provider returned HTTP {code}.",
        )
    if isinstance(exc, IntegrityError):
        return (
            REASON_DATABASE,
            500,
            "A database constraint stopped saving pulled points.",
        )
    if isinstance(exc, OperationalError):
        return (
            REASON_DATABASE,
            500,
            "The database was unavailable while saving pulled data.",
        )
    if isinstance(exc, SQLAlchemyError):
        return REASON_DATABASE, 500, "A database error stopped the pull."
    return REASON_UNEXPECTED, 500, "The pull failed with an unexpected error."


def _is_token_url(exc: httpx.HTTPStatusError) -> bool:
    try:
        url = str(exc.request.url) if exc.request is not None else ""
    except Exception:  # noqa: BLE001 — best-effort classification only
        return False
    return any(marker in url for marker in _TOKEN_HOST_MARKERS)


@dataclass(frozen=True)
class PullFailure:
    reason: str
    status_code: int
    message: str
    guidance: str
    error_id: str
    failed_date: str | None
    range_start: str | None
    range_end: str | None
    completed_dates: list[str]

    def as_detail(self) -> dict:
        detail = {
            "message": self.message,
            "reason": self.reason,
            "guidance": self.guidance,
            "error_id": self.error_id,
            "completed_dates": list(self.completed_dates),
        }
        if self.failed_date:
            detail["failed_date"] = self.failed_date
        if self.range_start:
            detail["range_start"] = self.range_start
        if self.range_end:
            detail["range_end"] = self.range_end
        return detail


def build_pull_failure(
    exc: BaseException,
    *,
    failed_date: date | None,
    range_start: date | None,
    range_end: date | None,
    completed_dates: list[str],
    error_id: str | None = None,
) -> PullFailure:
    error_id = error_id or new_error_id()
    reason, status, msg = classify_exception(exc)
    fd = failed_date.isoformat() if isinstance(failed_date, date) else None
    message = f"Pull failed on {fd}: {msg}" if fd else f"Pull failed: {msg}"
    if completed_dates:
        n = len(completed_dates)
        message += f" {n} earlier day{'s' if n != 1 else ''} in this request were saved."
    return PullFailure(
        reason=reason,
        status_code=status,
        message=message,
        guidance=GUIDANCE[reason],
        error_id=error_id,
        failed_date=fd,
        range_start=range_start.isoformat() if isinstance(range_start, date) else None,
        range_end=range_end.isoformat() if isinstance(range_end, date) else None,
        completed_dates=list(completed_dates),
    )


def persist_day_error(db: Session, account_id: int, d: date, reason: str, error_id: str) -> None:
    """Best-effort: mark the failed local day so nightly drain doesn't look like it's still pending.

    Swallows persistence failures — the HTTP error is the researcher-facing signal.
    Detail is reason + ref only (no exception text).
    """
    from app.consolidation import _get_or_create_state

    try:
        row = _get_or_create_state(db, account_id, d)
        row.status = "error"
        row.detail = f"{reason} ref {error_id}"
        row.completed_at = datetime.utcnow()
        db.commit()
    except Exception:  # noqa: BLE001 — never mask the original pull failure
        db.rollback()
        log.exception(
            "could not persist consolidate error state error_id=%s account_id=%s date=%s",
            error_id,
            account_id,
            d.isoformat(),
        )


def run_on_demand_range(
    db: Session,
    account,
    start: date,
    end: date,
    consolidate_fn,
    *,
    subject_id: int,
) -> list[dict]:
    """Pull each local day in `[start, end]`. On an unexpected exception, log + raise HTTPException.

    Days that `consolidate_fn` *returns* (including `status=error` for a revoked grant) are
    recorded and the loop continues — that is existing behavior. Only *raised* exceptions
    abort the request, after any already-committed days are listed in `completed_dates`.
    """
    days: list[dict] = []
    account_id = account.id
    provider = getattr(account, "provider", None)
    d = start
    while d <= end:
        try:
            state = consolidate_fn(db, account, d)
            days.append(
                {"date": d.isoformat(), "status": state.status, "detail": state.detail}
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — classified; traceback stays in logs
            db.rollback()
            failure = build_pull_failure(
                exc,
                failed_date=d,
                range_start=start,
                range_end=end,
                completed_dates=[row["date"] for row in days],
            )
            log.exception(
                "on-demand consolidate failed error_id=%s subject_id=%s account_id=%s "
                "provider=%s failed_date=%s reason=%s",
                failure.error_id,
                subject_id,
                account_id,
                provider,
                d.isoformat(),
                failure.reason,
            )
            persist_day_error(db, account_id, d, failure.reason, failure.error_id)
            raise HTTPException(
                status_code=failure.status_code, detail=failure.as_detail()
            ) from None
        d += timedelta(days=1)
    return days
