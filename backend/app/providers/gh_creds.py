"""Resolve which Google credential set to use for a study or account.

Studies enroll under a `GoogleCredentialSet` (one GCP project); a `ProviderAccount` pins the set
that *issued* its token. Any blank field on a set falls back to the global env `Settings`, and an
unassigned study/account falls back entirely to global — so existing subjects keep working.

Use `resolve_for_study` at enrollment (the study's current set) and `resolve_for_account` for
refresh/revoke (the account's pinned, issuing set).
"""

import json
import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.crypto import decrypt
from app.models import GoogleCredentialSet, ProviderAccount, Study

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GHCreds:
    """Resolved Google credentials for one project. `source` is 'global' or 'set:<id>' (logging)."""

    client_id: str
    client_secret: str
    scopes: str
    redirect_uri: str
    project_id: str
    project_number: str
    subscriber_id: str
    subscription_policy: str
    subscription_data_types: str
    webhook_secret: str
    sa_json: dict | None
    source: str


def _global() -> GHCreds:
    s = get_settings()
    return GHCreds(
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=s.google_health_scopes,
        redirect_uri=s.oauth_redirect_uri,
        project_id=s.gh_project_id,
        project_number=s.gh_project_number,
        subscriber_id=s.gh_subscriber_id,
        subscription_policy=s.gh_subscription_create_policy,
        subscription_data_types=s.gh_subscription_data_types,
        webhook_secret=s.webhook_secret,
        sa_json=None,
        source="global",
    )


def _pick(value, fallback):
    """Per-field fallback: use the set's value unless it's blank/None."""
    return value if value not in (None, "") else fallback


def _from_set(cset: GoogleCredentialSet) -> GHCreds:
    s = get_settings()
    sa = None
    if cset.sa_json:
        try:
            sa = json.loads(decrypt(cset.sa_json))
        except Exception:  # never let a bad blob break enrollment/refresh resolution
            log.exception("credential set %s: unreadable sa_json", cset.id)
    return GHCreds(
        client_id=_pick(cset.oauth_client_id, s.google_client_id),
        client_secret=_pick(decrypt(cset.oauth_client_secret), s.google_client_secret),
        scopes=_pick(cset.health_scopes, s.google_health_scopes),
        redirect_uri=s.oauth_redirect_uri,  # shared host path across all projects
        project_id=_pick(cset.gh_project_id, s.gh_project_id),
        project_number=_pick(cset.gh_project_number, s.gh_project_number),
        subscriber_id=_pick(cset.gh_subscriber_id, s.gh_subscriber_id),
        subscription_policy=_pick(cset.gh_subscription_create_policy, s.gh_subscription_create_policy),
        subscription_data_types=_pick(cset.gh_subscription_data_types, s.gh_subscription_data_types),
        webhook_secret=_pick(decrypt(cset.webhook_secret), s.webhook_secret),
        sa_json=sa,
        source=f"set:{cset.id}",
    )


def resolve_set(db: Session, set_id: int | None) -> GHCreds:
    if set_id is None:
        return _global()
    cset = db.get(GoogleCredentialSet, set_id)
    if cset is None:
        log.warning("credential_set_id %s not found; falling back to global creds", set_id)
        return _global()
    return _from_set(cset)


def resolve_for_study(db: Session, study_id: int | None) -> GHCreds:
    """Enrollment: the study's *current* credential set (or global)."""
    study = db.get(Study, study_id) if study_id is not None else None
    return resolve_set(db, study.credential_set_id if study else None)


def resolve_for_account(db: Session, account: ProviderAccount) -> GHCreds:
    """Refresh/revoke: the account's *pinned* (issuing) credential set (or global)."""
    return resolve_set(db, account.credential_set_id)
