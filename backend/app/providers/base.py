"""Provider protocol shared by per-provider OAuth modules.

Milestone 1 implements only `fitbit_gh`. Garmin (OAuth1a) slots in later as another
module satisfying this protocol where it can; Garmin has no refresh tokens and no
subscription API, so those methods are allowed to no-op / raise NotImplementedError.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class TokenResult:
    """Normalized token-exchange/refresh result."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None
    provider_user_id: str | None
    raw: dict


class Provider(Protocol):
    """OAuth + subscription surface a provider module must expose."""

    name: str

    def start_auth(self) -> tuple[str, str, str]:
        """Return (authorization_url, state, code_verifier) for a new enrollment."""
        ...

    def exchange(self, code: str, code_verifier: str) -> TokenResult:
        """Exchange an authorization code for tokens."""
        ...

    def refresh(self, refresh_token: str) -> TokenResult:
        """Refresh an access token."""
        ...
