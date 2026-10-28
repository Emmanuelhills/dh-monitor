"""Encrypted secret store.

Secrets are encrypted with Fernet using ``DHM_ENCRYPTION_KEY`` (kept outside the database,
e.g. in the deployment's secret manager). The API only ever reports whether a secret is set.
"""

import json

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SecretValue

SES_CREDENTIALS = "ses_credentials"
RESEND_CREDENTIALS = "resend_credentials"


class SecretStoreError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().encryption_key
    if not key:
        raise SecretStoreError("DHM_ENCRYPTION_KEY is not configured; secrets cannot be stored.")
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise SecretStoreError("DHM_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def put_secret(db: Session, name: str, value: dict) -> None:
    token = _fernet().encrypt(json.dumps(value).encode()).decode()
    existing = db.get(SecretValue, name)
    if existing:
        existing.ciphertext = token
    else:
        db.add(SecretValue(name=name, ciphertext=token))


def get_secret(db: Session, name: str) -> dict | None:
    row = db.get(SecretValue, name)
    if row is None:
        return None
    try:
        return json.loads(_fernet().decrypt(row.ciphertext.encode()))
    except InvalidToken as exc:
        raise SecretStoreError(f"Secret '{name}' cannot be decrypted with the current key.") from exc


def has_secret(db: Session, name: str) -> bool:
    return db.get(SecretValue, name) is not None


def delete_secret(db: Session, name: str) -> None:
    row = db.get(SecretValue, name)
    if row:
        db.delete(row)
