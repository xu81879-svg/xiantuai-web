#!/usr/bin/env python3
"""Validate Railway-style environment configuration without contacting Railway.

The script parses an env file, normalizes only in-memory values, creates a
SQLAlchemy Engine, and inspects its pool configuration. It never opens a DB
connection and never prints secret values.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool


REQUIRED = (
    "ENVIRONMENT",
    "DATABASE_URL",
    "PGSSLMODE",
    "AUTO_CREATE_SCHEMA",
    "SEED_DEMO_USER",
)
PLACEHOLDER_RE = re.compile(r"(?:\$\{\{|\}\}|请配置|请替换|你的 Railway|<[^>]+>|TODO|CHANGE_ME)")
VALID_PG_SSLMODES = {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}


def clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("export ") and "=" not in line:
            raise ValueError(f"第 {line_number} 行不是 KEY=VALUE 格式")
        line = line.removeprefix("export ")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"第 {line_number} 行变量名无效: {key}")
        values[key] = clean_value(value)
    return values


def normalize_database_url(raw: str, environment: str, sslmode: str) -> str:
    raw = clean_value(raw)
    if not raw:
        raise ValueError("DATABASE_URL 为空")
    if "${{" in raw or "}}" in raw:
        raise ValueError("DATABASE_URL 仍是未解析的 Railway Reference Variable")
    if raw.startswith("postgresql+asyncpg://"):
        raw = "postgresql+psycopg://" + raw.removeprefix("postgresql+asyncpg://")
    elif raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw.removeprefix("postgres://")
    elif raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw.removeprefix("postgresql://")
    if environment == "production" and raw.startswith("sqlite"):
        raise ValueError("生产环境禁止使用 SQLite DATABASE_URL")
    if not (raw.startswith("sqlite://") or raw.startswith("postgresql+psycopg://")):
        raise ValueError("DATABASE_URL 必须是 sqlite:// 或 PostgreSQL URL")
    if raw.startswith("postgresql+psycopg://") and "sslmode=" not in raw:
        raw += ("&" if "?" in raw else "?") + f"sslmode={sslmode}"
    return raw


def check(values: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for key in REQUIRED:
        if not values.get(key):
            errors.append(f"{key} 未设置")
    for key, value in values.items():
        if PLACEHOLDER_RE.search(value):
            errors.append(f"{key} 含有占位符或未解析模板")
    environment = values.get("ENVIRONMENT", "development").lower()
    sslmode = values.get("PGSSLMODE", "")
    if environment not in {"development", "test", "staging", "production"}:
        errors.append("ENVIRONMENT 必须是 development、test、staging 或 production")
    if sslmode not in VALID_PG_SSLMODES:
        errors.append("PGSSLMODE 不是有效的 PostgreSQL sslmode")
    for key in ("AUTO_CREATE_SCHEMA", "SEED_DEMO_USER"):
        if values.get(key, "").lower() not in {"true", "false"}:
            errors.append(f"{key} 必须是 true 或 false")
    if environment == "production":
        for key in ("AUTO_CREATE_SCHEMA", "SEED_DEMO_USER"):
            if values.get(key, "").lower() != "false":
                errors.append(f"生产环境 {key} 必须为 false")
    if values.get("DATABASE_URL"):
        try:
            normalized = normalize_database_url(values["DATABASE_URL"], environment, sslmode)
            parsed = urlsplit(normalized)
            if parsed.scheme == "postgresql+psycopg" and (not parsed.hostname or not parsed.path.strip("/")):
                errors.append("PostgreSQL DATABASE_URL 缺少主机或数据库名")
            if parsed.scheme == "sqlite" and environment == "production":
                errors.append("生产环境检测到 SQLite 回退")
        except ValueError as exc:
            errors.append(str(exc))
    if values.get("DATABASE_URL", "").startswith(('"', "'")):
        warnings.append("DATABASE_URL 两侧存在引号；脚本会在内存中清理，建议在 Railway 使用 Add Reference")
    return errors, warnings


def inspect_pool(values: dict[str, str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        url = normalize_database_url(
            values.get("DATABASE_URL", ""),
            values.get("ENVIRONMENT", "development").lower(),
            values.get("PGSSLMODE", "prefer"),
        )
        is_postgres = url.startswith("postgresql+psycopg://")
        connect_args: dict[str, Any] = {"connect_timeout": 10} if is_postgres else {"check_same_thread": False}
        engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        if not engine.pool._pre_ping:
            errors.append("连接池 pool_pre_ping 未启用")
        if is_postgres and not isinstance(engine.pool, QueuePool):
            errors.append(f"PostgreSQL 未使用 QueuePool，实际为 {type(engine.pool).__name__}")
        if is_postgres:
            query = parse_qs(urlsplit(url).query)
            if query.get("sslmode", [""])[0] not in VALID_PG_SSLMODES:
                errors.append("最终 PostgreSQL URL 的 sslmode 无效")
        print(f"✓ SQLAlchemy URL 格式有效（{engine.url.get_backend_name()}）")
        print(f"✓ pool_pre_ping=true，连接池类型={type(engine.pool).__name__}")
        print("✓ 未建立数据库连接（本脚本不会访问 Railway）")
    except Exception as exc:  # noqa: BLE001 - convert dependency/config errors to a safe CLI result
        errors.append(f"无法创建 SQLAlchemy Engine: {exc}")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="本地检查 Railway 环境变量格式和数据库连接池配置")
    parser.add_argument("--file", default="railway.env", help="要检查的 env 文件，默认 railway.env")
    parser.add_argument("--allow-missing-file", action="store_true", help="文件不存在时改用当前进程环境变量")
    args = parser.parse_args()
    path = Path(args.file)
    if path.exists():
        try:
            values = parse_env_file(path)
        except (OSError, ValueError) as exc:
            print(f"✗ 无法读取环境文件: {exc}", file=sys.stderr)
            return 2
        print(f"本地预检文件: {path}")
    elif args.allow_missing_file:
        values = {key: os.getenv(key, "") for key in REQUIRED}
        print("本地预检来源: 当前进程环境变量")
    else:
        print(f"✗ 环境文件不存在: {path}（可使用 --allow-missing-file 检查当前环境）", file=sys.stderr)
        return 2

    errors, warnings = check(values)
    pool_errors, pool_warnings = inspect_pool(values)
    errors.extend(pool_errors)
    warnings.extend(pool_warnings)
    for warning in warnings:
        print(f"! {warning}")
    for error in errors:
        print(f"✗ {error}", file=sys.stderr)
    print(f"检查完成：{len(errors)} 个错误，{len(warnings)} 个提示")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
