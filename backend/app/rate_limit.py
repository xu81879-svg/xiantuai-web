from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Iterable

from fastapi import HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger("xiantu.auth_rate_limit")
_LOCAL_COUNTS: dict[str, tuple[float, int]] = {}
_LOCAL_LOCK = threading.Lock()
_REDIS: Redis | None = None
_REDIS_URL: str | None = None
_WARNED_LOCAL_FALLBACK = False
_REDIS_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return count
"""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def _local_increment(key: str, window_seconds: int) -> int:
    now = time.monotonic()
    with _LOCAL_LOCK:
        if len(_LOCAL_COUNTS) > 10_000:
            for old_key, (expires_at, _) in list(_LOCAL_COUNTS.items()):
                if expires_at <= now:
                    _LOCAL_COUNTS.pop(old_key, None)
        expires_at, count = _LOCAL_COUNTS.get(key, (now + window_seconds, 0))
        if expires_at <= now:
            expires_at, count = now + window_seconds, 0
        count += 1
        _LOCAL_COUNTS[key] = (expires_at, count)
        return count


def _increment(key: str, window_seconds: int) -> int:
    global _REDIS, _REDIS_URL, _WARNED_LOCAL_FALLBACK
    url = (os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL") or "").strip()
    if url:
        if _REDIS is None or url != _REDIS_URL:
            _REDIS = Redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5, decode_responses=True)
            _REDIS_URL = url
        try:
            return int(_REDIS.eval(_REDIS_SCRIPT, 1, key, window_seconds))
        except RedisError as exc:
            if not _WARNED_LOCAL_FALLBACK:
                logger.warning("shared auth rate-limit store unavailable; using process-local fallback (%s)", type(exc).__name__)
                _WARNED_LOCAL_FALLBACK = True
    elif os.getenv("ENVIRONMENT", "development").lower() == "production" and not _WARNED_LOCAL_FALLBACK:
        logger.warning("REDIS_URL is not configured; auth rate limits are process-local")
        _WARNED_LOCAL_FALLBACK = True
    return _local_increment(key, window_seconds)


def enforce_auth_rate_limit(request: Request, action: str, email: str) -> None:
    """Apply fixed-window limits to normalized-email and client-IP hashes."""
    policies: dict[str, tuple[int, int, int, int]] = {
        "login": (30, 300, 8, 300),
        "register": (5, 3600, 3, 3600),
        "resend_verification": (5, 3600, 3, 3600),
    }
    if action not in policies:
        raise ValueError("unknown auth rate-limit action")
    ip_limit, ip_window, email_limit, email_window = policies[action]
    client_ip = request.client.host if request.client else "unknown"
    email_key = _digest(email.strip().lower())
    checks: Iterable[tuple[str, int, int]] = (
        (f"xiantu:auth:{action}:ip:{_digest(client_ip)}", ip_limit, ip_window),
        (f"xiantu:auth:{action}:email:{email_key}", email_limit, email_window),
    )
    for key, limit, window in checks:
        if _increment(key, window) > limit:
            raise HTTPException(
                status_code=429,
                detail="请求过于频繁，请稍后重试",
                headers={"Retry-After": str(window)},
            )


def enforce_resource_rate_limit(request: Request, action: str, account_id: str) -> None:
    """Apply hourly per-account and per-IP limits to expensive media actions."""
    policies: dict[str, tuple[int, int]] = {
        "generation": (12, 40),
        "recognition": (20, 60),
    }
    if action not in policies:
        raise ValueError("unknown resource rate-limit action")
    account_limit, ip_limit = policies[action]
    client_ip = request.client.host if request.client else "unknown"
    window = 3600
    checks: Iterable[tuple[str, int]] = (
        (f"xiantu:resource:{action}:ip:{_digest(client_ip)}", ip_limit),
        (f"xiantu:resource:{action}:account:{_digest(account_id)}", account_limit),
    )
    for key, limit in checks:
        if _increment(key, window) > limit:
            raise HTTPException(
                status_code=429,
                detail="图片服务请求次数已达上限，请稍后重试",
                headers={"Retry-After": str(window)},
            )
