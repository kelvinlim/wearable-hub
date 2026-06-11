"""Token encryption at rest (Fernet) — improvement over prior plaintext storage.

Use `encrypt`/`decrypt` for the `access_token` / `refresh_token` columns on
`provider_accounts`. The key lives in `FERNET_KEY` (env), never in the DB.
"""

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not set. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode())


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a token for storage. Passes None through unchanged."""
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a stored token. Passes None through unchanged."""
    if ciphertext is None:
        return None
    return _fernet().decrypt(ciphertext.encode()).decode()
