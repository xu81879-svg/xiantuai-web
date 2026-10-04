from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

PASSWORDS = PasswordHasher()
ALGORITHM = "HS256"


def secret_key() -> str:
    value = os.getenv("JWT_SECRET", "dev-only-change-this-secret")
    if os.getenv("ENVIRONMENT", "development") == "production" and value == "dev-only-change-this-secret":
        raise RuntimeError("JWT_SECRET must be configured in production")
    return value


def hash_password(password: str) -> str:
    return PASSWORDS.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORDS.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_access_token(user_id: str) -> str:
    minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
    payload = {"sub": user_id, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)}
    return jwt.encode(payload, secret_key(), algorithm=ALGORITHM)


def read_user_id(token: str) -> str | None:
    try:
        payload = jwt.decode(token, secret_key(), algorithms=[ALGORITHM])
        value = payload.get("sub")
        return value if isinstance(value, str) else None
    except jwt.PyJWTError:
        return None
