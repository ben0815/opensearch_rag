"""Fernet-based encryption for sensitive app_settings values.

Set ENCRYPTION_KEY in infra/.env (generate once):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If ENCRYPTION_KEY is not set: encrypt() and decrypt() are no-ops.
"""
import os
from cryptography.fernet import Fernet, InvalidToken

_KEY_ENV = "ENCRYPTION_KEY"
_PREFIX = "enc:"


def _get_fernet() -> Fernet | None:
    key = os.getenv(_KEY_ENV, "")
    if not key:
        return None
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    """Encrypt value and return 'enc:<token>'. No-op if ENCRYPTION_KEY not configured."""
    f = _get_fernet()
    if f is None:
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt 'enc:<token>' to plaintext. Returns value unchanged if not encrypted or no key."""
    if not value.startswith(_PREFIX):
        return value
    f = _get_fernet()
    if f is None:
        return value
    try:
        return f.decrypt(value[len(_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Ungültiger Verschlüsselungsschlüssel oder beschädigte Daten") from exc
