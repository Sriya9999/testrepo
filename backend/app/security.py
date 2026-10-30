import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

_hasher = PasswordHasher()
JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def validate_password_strength(password: str) -> str | None:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if password.lower() == password or password.upper() == password or not any(c.isdigit() for c in password):
        return "Password must mix upper- and lower-case letters and include a number."
    return None


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _encode(claims: dict[str, Any], ttl: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(payload, get_settings().secret_key, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(
        {"sub": str(user_id), "type": "access"}, timedelta(minutes=get_settings().access_token_minutes)
    )


def create_mfa_challenge(user_id: uuid.UUID) -> str:
    return _encode({"sub": str(user_id), "type": "mfa_challenge"}, timedelta(minutes=5))


def create_state_token(data: dict[str, Any], minutes: int = 15) -> str:
    """Signed, short-lived state for OAuth round-trips."""
    return _encode({**data, "type": "oauth_state"}, timedelta(minutes=minutes))


@lru_cache
def _fernet() -> Fernet:
    key = hashlib.sha256(get_settings().token_encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:  # key rotated or data corrupted
        raise ValueError("Stored credential could not be decrypted") from exc


def hmac_sha256_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
