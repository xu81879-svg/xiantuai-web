import pytest

from app.database import _clean_env_value, database_url


def test_clean_env_value_removes_railway_style_outer_quotes():
    assert _clean_env_value('"postgresql://user:pass@host/db"') == "postgresql://user:pass@host/db"
    assert _clean_env_value("'postgresql://user:pass@host/db'") == "postgresql://user:pass@host/db"
    assert _clean_env_value("  sqlite:///./test.db  ") == "sqlite:///./test.db"


def test_database_url_accepts_quoted_postgres_reference(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", '"postgresql://user:pass@host/db"')
    monkeypatch.setenv("PGSSLMODE", "require")
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert database_url() == "postgresql+psycopg://user:pass@host/db?sslmode=require"


def test_production_refuses_missing_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="DATABASE_URL must be configured"):
        database_url()


def test_unresolved_railway_reference_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", '${{Postgres.DATABASE_URL}}')
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(RuntimeError, match="unresolved Railway reference"):
        database_url()
