"""Researcher/admin API: studies, subjects, consolidation, project ops, user/member mgmt.

Every route requires a researcher session (`get_current_user`). Access model: superusers do
anything; other researchers are scoped to studies they're a member of ('admin' manages the
study's subjects + members, 'member' is read-only). Project-level ops are superuser-only.
"""

import secrets
from datetime import date, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app import consolidation, garmin_backfill
from app.accounts import revoke_account
from app.config import get_settings
from app.db import get_db
from app.models import (
    ConsolidationState,
    DailyHealth,
    HealthData,
    HealthDataPoint,
    PairedDevice,
    ProjectSubscriber,
    ProviderAccount,
    Study,
    StudyMembership,
    Subject,
    Subscription,
    User,
)
from app.providers import fitbit_gh, garmin
from app.schemas import (
    MemberCreate,
    MemberOut,
    RegistrationCreate,
    RegistrationOut,
    StudyCreate,
    StudyOut,
    StudyUpdate,
    SubjectCreate,
    SubjectOut,
    SubjectStatusOut,
    SubjectUpdate,
    UserCreate,
    UserOut,
)
from app.security import (
    assert_study_admin,
    assert_study_view,
    get_current_user,
    require_superuser,
    study_id_for_subject,
)

router = APIRouter(prefix="/admin", tags=["admin"])

# Airline record-locator style: 6 chars, uppercase. Ambiguous glyphs (I, L, O, 0, 1) are
# excluded so subjects can't mis-key them. 31^6 ≈ 887M combinations (collisions retried below).
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6

# Known providers (a device registration's provider must be one of these).
_PROVIDERS = frozenset({fitbit_gh.NAME, garmin.NAME})


def _generate_entry_code(db: Session) -> str:
    """Generate a unique per-device entry code. Retries on the (rare) collision."""
    for _ in range(10):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
        if db.scalar(select(ProviderAccount).where(ProviderAccount.entry_code == code)) is None:
            return code
    raise HTTPException(status_code=500, detail="Could not allocate a unique entry code")


def _create_registration(db: Session, subject_id: int, provider: str) -> ProviderAccount:
    """Create a device registration (provider_account) with a fresh entry code. Refuses dups."""
    if provider not in _PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")
    existing = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.subject_id == subject_id,
            ProviderAccount.provider == provider,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail=f"Subject already has a {provider} registration"
        )
    acct = ProviderAccount(
        subject_id=subject_id, provider=provider, entry_code=_generate_entry_code(db)
    )
    db.add(acct)
    return acct


@router.post("/studies", response_model=StudyOut, status_code=201)
def create_study(
    payload: StudyCreate, db: Session = Depends(get_db), user: User = Depends(require_superuser)
) -> Study:
    """Create a study. `provider` (the wearable for all its subjects) is set here and IMMUTABLE."""
    if payload.provider not in _PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {payload.provider}")
    study = Study(
        name=payload.name,
        description=payload.description,
        provider=payload.provider,
        created_by_user_id=user.id,
    )
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


@router.get("/studies", response_model=list[StudyOut])
def list_studies(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Study]:
    if user.is_superuser:
        return list(db.scalars(select(Study).order_by(Study.id)))
    study_ids = list(
        db.scalars(select(StudyMembership.study_id).where(StudyMembership.user_id == user.id))
    )
    if not study_ids:
        return []
    return list(db.scalars(select(Study).where(Study.id.in_(study_ids)).order_by(Study.id)))


@router.patch("/studies/{study_id}", response_model=StudyOut)
def update_study(
    study_id: int,
    payload: StudyUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Study:
    """Update study settings (e.g. opt in to intraday heart-rate). Study admin or superuser.
    `provider` is intentionally not updatable here — it's fixed at creation (StudyUpdate omits it)."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_admin(db, user, study_id)
    if payload.ingest_intraday_hr is not None:
        study.ingest_intraday_hr = payload.ingest_intraday_hr
    if payload.ingest_intraday_hrv is not None:
        study.ingest_intraday_hrv = payload.ingest_intraday_hrv
    if payload.ingest_intraday_spo2 is not None:
        study.ingest_intraday_spo2 = payload.ingest_intraday_spo2
    if payload.ingest_intraday_activity is not None:
        study.ingest_intraday_activity = payload.ingest_intraday_activity
    if payload.ingest_intraday_stress is not None:
        study.ingest_intraday_stress = payload.ingest_intraday_stress
    db.commit()
    db.refresh(study)
    return study


@router.post("/studies/{study_id}/subjects", response_model=SubjectOut, status_code=201)
def create_subject(
    study_id: int,
    payload: SubjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subject:
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_admin(db, user, study_id)
    if payload.collection_end and payload.collection_start and payload.collection_end < payload.collection_start:
        raise HTTPException(status_code=400, detail="collection_end must be >= collection_start")
    subject = Subject(
        study_id=study_id,
        subject_label=payload.subject_label,
        participant_id=payload.participant_id,
        status="pending",
        collection_start=payload.collection_start,
        collection_end=payload.collection_end,
    )
    db.add(subject)
    db.flush()  # need subject.id for the registration
    # The device is fixed by the study: auto-create the one registration + its entry code.
    _create_registration(db, subject.id, study.provider)
    db.commit()
    db.refresh(subject)
    return subject


@router.patch("/subjects/{subject_id}", response_model=SubjectOut)
def update_subject(
    subject_id: int,
    payload: SubjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Subject:
    """Edit a subject's label, Study ID, and optional data-collection window. Study admin only.
    Only fields present in the body are applied (a present null clears that field)."""
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    assert_study_admin(db, user, subj.study_id)

    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(subj, key, value)
    # Validate the resulting window (whichever bound was just changed).
    if subj.collection_start and subj.collection_end and subj.collection_end < subj.collection_start:
        raise HTTPException(status_code=400, detail="collection_end must be >= collection_start")

    db.commit()
    db.refresh(subj)
    return subj


@router.delete("/subjects/{subject_id}", status_code=204)
def delete_subject(
    subject_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    """Delete a subject that hasn't linked a wearable yet. Study admin only. Refuses if any of
    the subject's provider accounts is registered (revoke first). Cleans up any stray rows."""
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    assert_study_admin(db, user, subj.study_id)

    accounts = list(db.scalars(select(ProviderAccount).where(ProviderAccount.subject_id == subject_id)))
    if any(a.registered for a in accounts):
        raise HTTPException(
            status_code=409, detail="Subject is linked — revoke their access before deleting."
        )
    acct_ids = [a.id for a in accounts]
    if acct_ids:
        for model in (Subscription, DailyHealth, HealthDataPoint, ConsolidationState, HealthData, PairedDevice):
            db.execute(delete(model).where(model.provider_account_id.in_(acct_ids)))
        db.execute(delete(ProviderAccount).where(ProviderAccount.id.in_(acct_ids)))
    db.delete(subj)
    db.commit()


@router.post("/subjects/{subject_id}/registrations", response_model=RegistrationOut, status_code=201)
def add_registration(
    subject_id: int,
    payload: RegistrationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProviderAccount:
    """(Re-)create a subject's device registration + entry code. Study admin.

    The device is fixed by the study, so the provider must match `study.provider`; a subject has
    exactly one registration. Normally created automatically at subject creation — this endpoint is
    for re-issuing a code if the registration was deleted."""
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    assert_study_admin(db, user, subj.study_id)
    study = db.get(Study, subj.study_id)
    if study and payload.provider != study.provider:
        raise HTTPException(
            status_code=409,
            detail=f"This study uses {study.provider}; cannot register a {payload.provider} device.",
        )
    acct = _create_registration(db, subject_id, study.provider if study else payload.provider)
    db.commit()
    db.refresh(acct)
    return acct


@router.delete("/subjects/{subject_id}/registrations/{registration_id}", status_code=204)
def delete_registration(
    subject_id: int,
    registration_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete an unlinked device registration + its stray data. Revoke a linked one first."""
    acct = db.get(ProviderAccount, registration_id)
    if acct is None or acct.subject_id != subject_id:
        raise HTTPException(status_code=404, detail="Registration not found")
    subj = db.get(Subject, subject_id)
    assert_study_admin(db, user, subj.study_id)
    if acct.registered:
        raise HTTPException(
            status_code=409, detail="Device is linked — revoke its access before deleting."
        )
    for model in (Subscription, DailyHealth, HealthDataPoint, ConsolidationState, HealthData, PairedDevice):
        db.execute(delete(model).where(model.provider_account_id == acct.id))
    db.delete(acct)
    db.commit()


@router.post("/subscriber", status_code=201)
def ensure_project_subscriber(
    db: Session = Depends(get_db), _: User = Depends(require_superuser)
) -> dict:
    """Tier-1 (one-time): register the project's webhook subscriber with project credentials.

    Idempotent at the app level — upserts the `project_subscribers` row. Run once after the
    service account is configured. Returns Google's raw response (or surfaces its error) so
    the exact subscriber shape can be confirmed against the live API.
    """
    settings = get_settings()
    raw: dict = {}
    try:
        raw = fitbit_gh.register_subscriber()
    except (fitbit_gh.ProjectCredentialsError, fitbit_gh.InvalidDataTypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        # 409 ALREADY_EXISTS → idempotent no-op: the subscriber is already registered, so
        # fall through and reconcile our DB row from the canonical resource below.
        if exc.response.status_code != 409:
            # Pass Google's status + body straight through for debugging the real API.
            raise HTTPException(
                status_code=502,
                detail={"google_status": exc.response.status_code, "google_body": exc.response.text},
            ) from exc

    # `raw` may be the subscriber resource OR a long-running Operation (async endpoint
    # verification). Don't parse it — re-read the canonical subscriber by its known id.
    resource = fitbit_gh.get_subscriber() or {}
    subscriber_name = resource.get("name")  # full path: projects/{num}/subscribers/{id}
    # Tier-2 create_subscription() interpolates this into the URL after /subscribers/, so it
    # must be the SHORT client id, not the full resource name.
    subscriber_id = settings.gh_subscriber_id

    row = db.scalar(
        select(ProjectSubscriber).where(ProjectSubscriber.project_id == settings.gh_project_id)
    )
    if row is None:
        row = ProjectSubscriber(project_id=settings.gh_project_id)
        db.add(row)
    row.subscriber_id = subscriber_id
    row.subscriber_name = subscriber_name
    row.webhook_url = settings.webhook_public_url
    row.raw_json = resource or raw
    db.commit()
    db.refresh(row)
    return {
        "project_id": row.project_id,
        "subscriber_id": row.subscriber_id,
        "subscriber_name": row.subscriber_name,
        "webhook_url": row.webhook_url,
    }


@router.get("/subscriber")
def get_project_subscriber(
    db: Session = Depends(get_db), _: User = Depends(require_superuser)
) -> dict:
    """Show the registered project subscriber, if any."""
    settings = get_settings()
    row = db.scalar(
        select(ProjectSubscriber).where(ProjectSubscriber.project_id == settings.gh_project_id)
    )
    if row is None:
        return {"project_id": settings.gh_project_id, "registered": False}
    return {
        "project_id": row.project_id,
        "registered": bool(row.subscriber_id),
        "subscriber_id": row.subscriber_id,
        "subscriber_name": row.subscriber_name,
        "webhook_url": row.webhook_url,
    }


@router.post("/subscriptions/sync")
def sync_subscriptions(
    subject_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_superuser),
) -> dict:
    """Reconcile per-user (Tier-2) subscriptions from Google into the local DB.

    Under AUTOMATIC policy Google creates a subscription per subject on consent; its `user`
    field carries the public `healthUserId` (which we can't get from the subject's token).
    This LISTs those subscriptions, upserts `subscriptions` rows, and links each `healthUserId`
    to its `provider_account` so inbound webhook data resolves to the right subject.

    Linking is conservative — never guessed:
    - A subscription whose `healthUserId` already matches an account links directly.
    - `subject_id` (optional): bind the single still-unlinked subscription to that subject's
      registered account. Use this right after enrolling a specific subject.
    - Otherwise, only when exactly one registered account and one subscription are both still
      unlinked (the simple sequential-enrollment case) are they paired. Ambiguity is reported.
    """
    settings = get_settings()
    sub_row = db.scalar(
        select(ProjectSubscriber).where(ProjectSubscriber.project_id == settings.gh_project_id)
    )
    if sub_row is None or not sub_row.subscriber_id:
        raise HTTPException(
            status_code=400, detail="No project subscriber registered; POST /admin/subscriber first."
        )
    try:
        google_subs = fitbit_gh.list_subscriptions(sub_row.subscriber_id)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail={"google_status": exc.response.status_code, "google_body": exc.response.text},
        ) from exc

    # Upsert a row per Google subscription; link directly when the healthUserId is known.
    for gs in google_subs:
        name = gs.get("name")
        hid = fitbit_gh.parse_health_user_id(gs)
        row = db.scalar(
            select(Subscription).where(Subscription.provider_subscription_id == name)
        )
        if row is None:
            row = Subscription(provider_subscription_id=name)
            db.add(row)
        row.subscriber_id = sub_row.subscriber_id
        row.health_user_id = hid
        row.data_types = gs.get("dataTypes")
        row.status = "active"
        if hid and row.provider_account_id is None:
            acct = db.scalar(
                select(ProviderAccount).where(
                    ProviderAccount.provider == fitbit_gh.NAME,
                    ProviderAccount.health_user_id == hid,
                )
            )
            if acct:
                row.provider_account_id = acct.id
    db.flush()

    linked: list[dict] = []

    def _link(sub: Subscription, acct: ProviderAccount) -> None:
        acct.health_user_id = sub.health_user_id
        sub.provider_account_id = acct.id
        linked.append(
            {"provider_account_id": acct.id, "subject_id": acct.subject_id,
             "health_user_id": sub.health_user_id}
        )

    unlinked_subs = list(
        db.scalars(
            select(Subscription).where(
                Subscription.provider_account_id.is_(None),
                Subscription.health_user_id.is_not(None),
            )
        )
    )
    unlinked_accts = list(
        db.scalars(
            select(ProviderAccount).where(
                ProviderAccount.provider == fitbit_gh.NAME,
                ProviderAccount.registered.is_(True),
                ProviderAccount.health_user_id.is_(None),
            )
        )
    )

    if subject_id is not None:
        # Deterministic: bind the single unlinked subscription to this subject's account.
        target = db.scalar(
            select(ProviderAccount).where(
                ProviderAccount.subject_id == subject_id,
                ProviderAccount.provider == fitbit_gh.NAME,
            )
        )
        if target is None:
            raise HTTPException(status_code=404, detail="No fitbit account for that subject")
        if target.health_user_id is None:
            if len(unlinked_subs) != 1:
                raise HTTPException(
                    status_code=409,
                    detail=f"Expected exactly 1 unlinked subscription, found {len(unlinked_subs)}",
                )
            _link(unlinked_subs[0], target)
            unlinked_subs, unlinked_accts = [], []
    elif len(unlinked_subs) == 1 and len(unlinked_accts) == 1:
        # Sequential-enrollment case: the one new subscription belongs to the one new account.
        _link(unlinked_subs[0], unlinked_accts[0])
        unlinked_subs, unlinked_accts = [], []

    db.commit()
    return {
        "google_subscriptions": len(google_subs),
        "linked": linked,
        "unlinked_subscriptions": len(unlinked_subs),
        "unlinked_accounts": len(unlinked_accts),
    }


@router.post("/subjects/{subject_id}/revoke")
def revoke_subject(
    subject_id: int,
    provider: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Revoke a subject's wearable authorization: revoke the grant at the provider, then mark the
    account(s) unregistered and drop their tokens. Idempotent. Requires study-admin.

    With `provider` set, revokes just that device; otherwise revokes every linked device.
    """
    assert_study_admin(db, user, study_id_for_subject(db, subject_id))
    accounts = _subject_accounts(db, subject_id)
    if provider is not None:
        accounts = [a for a in accounts if a.provider == provider]
    targets = [a for a in accounts if a.registered] or accounts
    if not targets:
        raise HTTPException(status_code=404, detail="No provider account for that subject")
    results = []
    for acct in targets:
        was_registered = acct.registered
        revoked_at_provider = revoke_account(db, acct)
        results.append(
            {
                "provider_account_id": acct.id,
                "provider": acct.provider,
                "was_registered": was_registered,
                "revoked_at_provider": revoked_at_provider,
                "registered": acct.registered,
            }
        )
    db.commit()
    return {"subject_id": subject_id, "revoked": results}


def _subject_accounts(db: Session, subject_id: int) -> list[ProviderAccount]:
    """All of a subject's device registrations (404 if the subject doesn't exist)."""
    if db.get(Subject, subject_id) is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return list(
        db.scalars(
            select(ProviderAccount)
            .where(ProviderAccount.subject_id == subject_id)
            .order_by(ProviderAccount.id)
        )
    )


def _require_account(db: Session, subject_id: int, provider: str) -> ProviderAccount:
    """The subject's registration for a specific provider (404 if none)."""
    acct = db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.subject_id == subject_id,
            ProviderAccount.provider == provider,
        )
    )
    if acct is None:
        if db.get(Subject, subject_id) is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        raise HTTPException(status_code=404, detail=f"No {provider} account for that subject")
    return acct


@router.post("/subjects/{subject_id}/consolidate")
def consolidate_subject(
    subject_id: int,
    start: date,
    end: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """On-demand: (re)build daily_health for a subject over [start, end] by pulling from Google.
    Used for backfilling history and verification. Idempotent per day. Requires study-admin."""
    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")
    if (end - start).days > 120:
        raise HTTPException(status_code=400, detail="range too large (max 120 days)")
    assert_study_admin(db, user, study_id_for_subject(db, subject_id))
    # Consolidation is a Google *pull*; Garmin self-aggregates from pushes, so it has no pull path.
    acct = _require_account(db, subject_id, fitbit_gh.NAME)
    days = []
    d = start
    while d <= end:
        state = consolidation.consolidate_day(db, acct, d)
        days.append({"date": d.isoformat(), "status": state.status, "detail": state.detail})
        d += timedelta(days=1)
    return {"subject_id": subject_id, "provider_account_id": acct.id, "days": days}


@router.post("/subjects/{subject_id}/backfill")
def backfill_subject(
    subject_id: int,
    start: date,
    end: date,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """On-demand Garmin backfill: ask Garmin to re-push historical summaries over [start, end].

    Garmin-only — Fitbit/Google backfills via `/consolidate` (a pull); Garmin has no pull, so this
    fires `/backfill/{type}` requests instead. **Fully async**: the fan-out is spaced out + retries
    on Garmin's 429 throttle, so it runs in the **background** and this returns immediately with the
    queued shape. Data then arrives via the push webhooks (only for enabled webhook types). The
    range is chunked into <=90-day windows per Garmin's cap. Requires study-admin."""
    if end < start:
        raise HTTPException(status_code=400, detail="end must be >= start")
    if (end - start).days > 730:
        raise HTTPException(status_code=400, detail="range too large (max 2 years)")
    assert_study_admin(db, user, study_id_for_subject(db, subject_id))
    acct = _require_account(db, subject_id, garmin.NAME)
    background_tasks.add_task(garmin_backfill.run_backfill, acct.id, start, end)
    types = garmin_backfill.configured_types()
    windows = garmin_backfill.window_count(start, end)
    return {
        "subject_id": subject_id,
        "provider_account_id": acct.id,
        "queued": True,
        "types": types,
        "windows": windows,
        "requests": len(types) * windows,
    }


@router.post("/consolidate/run-due")
def consolidate_run_due(
    limit: int = 50, db: Session = Depends(get_db), _: User = Depends(require_superuser)
) -> dict:
    """Drain pending consolidation_state rows (the durable dirty-day queue). What cron calls."""
    return consolidation.consolidate_due(db, limit=limit)


@router.get("/subjects/{subject_id}/daily")
def list_daily(
    subject_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    """List a subject's consolidated daily rows (most recent first). Requires study view."""
    assert_study_view(db, user, study_id_for_subject(db, subject_id))
    provider_by_acct = {
        a.id: a.provider
        for a in db.scalars(
            select(ProviderAccount).where(ProviderAccount.subject_id == subject_id)
        )
    }
    rows = db.scalars(
        select(DailyHealth)
        .where(DailyHealth.subject_id == subject_id)
        .order_by(DailyHealth.local_date.desc())
    )
    return [
        {
            "date": r.local_date.isoformat(),
            "provider": provider_by_acct.get(r.provider_account_id),
            "steps": r.steps,
            "distance_m": r.distance_m,
            "calories": r.calories,
            "floors": r.floors,
            "sleep_minutes": r.sleep_minutes,
            "hr_avg": r.hr_avg,
            "resting_hr": r.resting_hr,
            "hrv_ms": r.hrv_ms,
            "spo2_avg": r.spo2_avg,
            "azm_total": r.azm_total,
            "mvpa_minutes": r.mvpa_minutes,
            "point_count": r.point_count,
            "metrics": r.metrics,
        }
        for r in rows
    ]


def _point_to_dict(r: HealthDataPoint) -> dict:
    """Serialize one intraday point; sleep includes its parsed stage architecture."""
    item = {
        "datatype": r.datatype,
        "start_time": r.start_time.isoformat() if r.start_time else None,
        "end_time": r.end_time.isoformat() if r.end_time else None,
        "value": r.value,
        "tz_offset_seconds": r.tz_offset_seconds,
    }
    if r.datatype == "sleep" and isinstance(r.payload, dict):
        stages = (r.payload.get("sleep") or {}).get("stages") or []
        item["stages"] = [
            {"type": s.get("type"), "start_time": s.get("startTime"), "end_time": s.get("endTime")}
            for s in stages
            if isinstance(s, dict)
        ]
    elif isinstance(r.payload, dict):
        # Downsampled buckets (steps/distance sum, SpO2 avg) carry aggregation metadata; surface
        # the sample count and, for SpO2, the bucket minimum (desaturation nadir) alongside `value`.
        for k in ("samples", "bucket_minutes", "spo2_min", "spo2_avg"):
            if k in r.payload:
                item[k] = r.payload[k]
    return item


@router.get("/subjects/{subject_id}/daily/{day}/points")
def list_day_points(
    subject_id: int,
    day: date,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Raw intraday data points for a subject on one local day (most granular). Study view.

    Note: floors/calories are rollup-only (no raw points); steps/distance/altitude/sleep/etc.
    have intraday points. `start_time`/`end_time` are UTC; `tz_offset_seconds` gives the local
    offset for display.
    """
    assert_study_view(db, user, study_id_for_subject(db, subject_id))
    accounts = _subject_accounts(db, subject_id)
    provider_by_acct = {a.id: a.provider for a in accounts}
    if not accounts:
        return []
    rows = db.scalars(
        select(HealthDataPoint)
        .where(
            HealthDataPoint.provider_account_id.in_(provider_by_acct.keys()),
            HealthDataPoint.local_date == day,
        )
        .order_by(HealthDataPoint.datatype, HealthDataPoint.start_time)
    )
    out = []
    for r in rows:
        item = _point_to_dict(r)
        item["provider"] = provider_by_acct.get(r.provider_account_id)
        out.append(item)
    return out


def _device_to_dict(r: PairedDevice) -> dict:
    return {
        "device_name": r.device_name,
        "device_type": r.device_type,
        "device_version": r.device_version,
        "battery_level": r.battery_level,
        "battery_status": r.battery_status,
        "last_sync_time": r.last_sync_time.isoformat() if r.last_sync_time else None,
        "mac_address": r.mac_address,
        "features": r.features,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _devices_for_account(db: Session, account_id: int) -> list[dict]:
    rows = db.scalars(
        select(PairedDevice)
        .where(PairedDevice.provider_account_id == account_id)
        .order_by(PairedDevice.device_type, PairedDevice.device_name)
    )
    return [_device_to_dict(r) for r in rows]


@router.get("/subjects/{subject_id}/devices")
def list_devices(
    subject_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[dict]:
    """A subject's paired devices (latest snapshot: battery, last sync, model). Study view.

    Snapshots are refreshed during consolidation of a recent day; battery/sync reflect the last
    such pull (`updated_at`). Empty if the subject's grant lacks the settings.readonly scope."""
    assert_study_view(db, user, study_id_for_subject(db, subject_id))
    accounts = _subject_accounts(db, subject_id)
    out: list[dict] = []
    for acct in accounts:
        for dev in _devices_for_account(db, acct.id):
            dev["provider"] = acct.provider
            out.append(dev)
    return out


@router.get("/subjects/{subject_id}/export")
def export_subject(
    subject_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Full JSON export for a subject: each local day's consolidated summary with its intraday
    points (incl. sleep stages) nested underneath. Optional [start, end] date filter. Study view."""
    assert_study_view(db, user, study_id_for_subject(db, subject_id))
    subj = db.get(Subject, subject_id)
    if subj is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    payload = _subject_export_payload(db, subj, start, end)
    payload["range"] = {
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    }
    return payload


def _subject_export_payload(
    db: Session, subj: Subject, start: date | None, end: date | None
) -> dict:
    """{subject, days[ summary + nested intraday points ]} for one subject across ALL its device
    registrations (each day/point tagged with its provider). Used by the subject and whole-study
    exports."""
    accounts = list(
        db.scalars(select(ProviderAccount).where(ProviderAccount.subject_id == subj.id))
    )
    subject = {
        "id": subj.id,
        "subject_label": subj.subject_label,
        "participant_id": subj.participant_id,
        "study_id": subj.study_id,
        "status": subj.status,
        "registrations": [
            {
                "provider": a.provider,
                "entry_code": a.entry_code,
                "registered": a.registered,
                "health_user_id": a.health_user_id,
            }
            for a in accounts
        ],
        "devices": [],
    }
    for a in accounts:
        for dev in _devices_for_account(db, a.id):
            dev["provider"] = a.provider
            subject["devices"].append(dev)
    if not accounts:
        return {"subject": subject, "days": []}

    acct_ids = [a.id for a in accounts]
    provider_by_acct = {a.id: a.provider for a in accounts}
    dq = select(DailyHealth).where(DailyHealth.provider_account_id.in_(acct_ids))
    pq = select(HealthDataPoint).where(HealthDataPoint.provider_account_id.in_(acct_ids))
    if start:
        dq = dq.where(DailyHealth.local_date >= start)
        pq = pq.where(HealthDataPoint.local_date >= start)
    if end:
        dq = dq.where(DailyHealth.local_date <= end)
        pq = pq.where(HealthDataPoint.local_date <= end)

    by_day: dict = {}
    for r in db.scalars(
        pq.order_by(HealthDataPoint.local_date, HealthDataPoint.datatype, HealthDataPoint.start_time)
    ):
        item = _point_to_dict(r)
        item["provider"] = provider_by_acct.get(r.provider_account_id)
        by_day.setdefault((r.provider_account_id, r.local_date), []).append(item)

    days = [
        {
            "date": d.local_date.isoformat(),
            "provider": provider_by_acct.get(d.provider_account_id),
            "tz_offset_seconds": d.tz_offset_seconds,
            "steps": d.steps,
            "distance_m": d.distance_m,
            "calories": d.calories,
            "floors": d.floors,
            "sleep_minutes": d.sleep_minutes,
            "hr_avg": d.hr_avg,
            "resting_hr": d.resting_hr,
            "hrv_ms": d.hrv_ms,
            "spo2_avg": d.spo2_avg,
            "azm_total": d.azm_total,
            "mvpa_minutes": d.mvpa_minutes,
            "metrics": d.metrics,
            "point_count": d.point_count,
            "points": by_day.get((d.provider_account_id, d.local_date), []),
        }
        for d in db.scalars(dq.order_by(DailyHealth.local_date, DailyHealth.provider_account_id))
    ]
    return {"subject": subject, "days": days}


@router.get("/studies/{study_id}/export")
def export_study(
    study_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Whole-study JSON export: every subject with their daily + intraday data. Study view."""
    study = db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_view(db, user, study_id)
    subjects_out = []
    for subj in db.scalars(select(Subject).where(Subject.study_id == study_id).order_by(Subject.id)):
        subjects_out.append(_subject_export_payload(db, subj, start, end))
    return {
        "study": {"id": study.id, "name": study.name, "description": study.description},
        "range": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "subjects": subjects_out,
    }


@router.get("/studies/{study_id}/subjects", response_model=list[SubjectStatusOut])
def list_subjects(
    study_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[SubjectStatusOut]:
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_view(db, user, study_id)
    subjects = db.scalars(
        select(Subject).where(Subject.study_id == study_id).order_by(Subject.id)
    )
    today = date.today()
    week_ago = today - timedelta(days=6)
    # A day "has data" if it carried any consolidated metric (a row alone isn't enough:
    # consolidate writes an empty row for out-of-range / no-data days too).
    has_data = or_(
        DailyHealth.point_count > 0,
        DailyHealth.steps.isnot(None),
        DailyHealth.calories.isnot(None),
        DailyHealth.sleep_minutes.isnot(None),
        DailyHealth.hr_avg.isnot(None),
    )
    out: list[SubjectStatusOut] = []
    for subj in subjects:
        accounts = list(
            db.scalars(
                select(ProviderAccount)
                .where(ProviderAccount.subject_id == subj.id)
                .order_by(ProviderAccount.id)
            )
        )
        item = SubjectStatusOut.model_validate(subj)
        item.registrations = [
            _registration_summary(db, subj, acct, today, week_ago, has_data) for acct in accounts
        ]
        item.registered = any(r.registered for r in item.registrations)
        _aggregate_registrations(item)
        out.append(item)
    return out


def _registration_summary(db, subj, acct, today, week_ago, has_data) -> RegistrationOut:
    """One device's battery + data-freshness summary for the list view."""
    reg = RegistrationOut(
        id=acct.id, provider=acct.provider, entry_code=acct.entry_code, registered=acct.registered
    )
    # Lowest-battery device (nulls last) — surfaces the most concerning one.
    dev = db.scalar(
        select(PairedDevice)
        .where(PairedDevice.provider_account_id == acct.id)
        .order_by(PairedDevice.battery_level.is_(None), PairedDevice.battery_level.asc())
    )
    if dev is not None:
        reg.battery_level = dev.battery_level
        reg.battery_status = dev.battery_status
        reg.battery_low = dev.battery_status in ("Low", "Empty") or (
            dev.battery_level is not None and dev.battery_level <= 20
        )

    reg.last_data_date = db.scalar(
        select(func.max(DailyHealth.local_date)).where(
            DailyHealth.provider_account_id == acct.id, has_data
        )
    )
    reg.days_with_data_7 = (
        db.scalar(
            select(func.count(func.distinct(DailyHealth.local_date))).where(
                DailyHealth.provider_account_id == acct.id,
                DailyHealth.local_date >= week_ago,
                DailyHealth.local_date <= today,
                has_data,
            )
        )
        or 0
    )

    # Stale only flags devices we'd *expect* fresh data from: linked and inside the subject's
    # collection window (a closed/not-yet-started window makes "no recent data" expected).
    in_window = not (
        (subj.collection_end and subj.collection_end < today)
        or (subj.collection_start and subj.collection_start > today)
    )
    reg.data_stale = bool(
        acct.registered
        and in_window
        and (reg.last_data_date is None or reg.last_data_date < today - timedelta(days=2))
    )
    return reg


def _aggregate_registrations(item: SubjectStatusOut) -> None:
    """Roll up the per-device summaries to the subject-level (most-concerning) fields."""
    regs = item.registrations
    if not regs:
        return
    # Lowest battery across devices (nulls last).
    batt = [r for r in regs if r.battery_level is not None]
    if batt:
        worst = min(batt, key=lambda r: r.battery_level)
        item.battery_level = worst.battery_level
        item.battery_status = worst.battery_status
    item.battery_low = any(r.battery_low for r in regs)
    dates = [r.last_data_date for r in regs if r.last_data_date is not None]
    item.last_data_date = max(dates) if dates else None
    item.days_with_data_7 = max((r.days_with_data_7 for r in regs), default=0)
    item.data_stale = any(r.data_stale for r in regs)


# --- Researcher (user) management — superuser only ------------------------------

@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_superuser)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_superuser)
) -> User:
    """Allowlist a researcher by email (they can then sign in with that Google account)."""
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail=f"{email} is already a researcher")
    user = User(email=email, name=payload.name, is_superuser=payload.is_superuser)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int, db: Session = Depends(get_db), me: User = Depends(require_superuser)
) -> None:
    if user_id == me.id:
        raise HTTPException(status_code=400, detail="cannot delete yourself")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    for m in db.scalars(select(StudyMembership).where(StudyMembership.user_id == user_id)):
        db.delete(m)
    db.delete(user)
    db.commit()


# --- Study membership — study admins (or superuser) -----------------------------

@router.get("/studies/{study_id}/members", response_model=list[MemberOut])
def list_members(
    study_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[MemberOut]:
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_admin(db, user, study_id)
    rows = db.execute(
        select(User, StudyMembership.role)
        .join(StudyMembership, StudyMembership.user_id == User.id)
        .where(StudyMembership.study_id == study_id)
        .order_by(User.id)
    )
    return [MemberOut(user_id=u.id, email=u.email, name=u.name, role=role) for u, role in rows]


@router.get("/studies/{study_id}/assignable-users", response_model=list[UserOut])
def list_assignable_users(
    study_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[User]:
    """Researchers a study admin can add to this study — i.e. those not already members.

    Study-admin scoped (not a global directory): only this study's admins/superusers can read it.
    Feeds the 'add staff' pulldown in the console."""
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_admin(db, user, study_id)
    member_ids = select(StudyMembership.user_id).where(StudyMembership.study_id == study_id)
    return list(
        db.scalars(select(User).where(User.id.not_in(member_ids)).order_by(User.email))
    )


@router.post("/studies/{study_id}/members", response_model=MemberOut, status_code=201)
def add_member(
    study_id: int,
    payload: MemberCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> MemberOut:
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_admin(db, user, study_id)
    if payload.role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'member'")
    email = payload.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    target = db.scalar(select(User).where(User.email == email))
    if target is None:
        # Onboard a brand-new researcher. Always a non-superuser — a study admin must never be able
        # to mint a superuser (that stays on the superuser-only POST /admin/users path).
        target = User(email=email, name=payload.name, is_superuser=False)
        db.add(target)
        db.flush()
    m = db.scalar(
        select(StudyMembership).where(
            StudyMembership.user_id == target.id, StudyMembership.study_id == study_id
        )
    )
    if m is None:
        m = StudyMembership(user_id=target.id, study_id=study_id, role=payload.role)
        db.add(m)
    else:
        m.role = payload.role
    db.commit()
    return MemberOut(user_id=target.id, email=target.email, name=target.name, role=payload.role)


@router.delete("/studies/{study_id}/members/{user_id}", status_code=204)
def remove_member(
    study_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    if db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    assert_study_admin(db, user, study_id)
    m = db.scalar(
        select(StudyMembership).where(
            StudyMembership.user_id == user_id, StudyMembership.study_id == study_id
        )
    )
    if m:
        db.delete(m)
        db.commit()
