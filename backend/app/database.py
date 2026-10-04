from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _clean_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def database_url() -> str:
    raw_value = os.getenv("DATABASE_URL")
    if raw_value is None or not _clean_env_value(raw_value):
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            raise RuntimeError("DATABASE_URL must be configured in production; refusing SQLite fallback")
        raw = "sqlite:///./xiantu.db"
    else:
        raw = _clean_env_value(raw_value)
    if "${{" in raw or "}}" in raw:
        raise RuntimeError("DATABASE_URL contains an unresolved Railway reference variable")
    if raw.startswith("postgresql+asyncpg://"):
        raw = "postgresql+psycopg://" + raw.removeprefix("postgresql+asyncpg://")
    elif raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw.removeprefix("postgres://")
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw.removeprefix("postgresql://")
    if raw.startswith("postgresql+psycopg://") and "sslmode=" not in raw:
        default_sslmode = "require" if os.getenv("ENVIRONMENT", "development").lower() == "production" else "prefer"
        sslmode = os.getenv("PGSSLMODE", default_sslmode)
        raw = f"{raw}{'&' if '?' in raw else '?'}sslmode={sslmode}"
    return raw


URL = database_url()
connect_args = {"check_same_thread": False} if URL.startswith("sqlite") else {"connect_timeout": 10}
engine = create_engine(URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_local_storage() -> None:
    storage_dir = Path(os.getenv("LOCAL_STORAGE_DIR", "./data"))
    storage_dir.mkdir(parents=True, exist_ok=True)
