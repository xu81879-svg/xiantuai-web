from __future__ import annotations

import os
from celery import Celery


def broker_url() -> str:
    return os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL") or "redis://localhost:6379/0"


celery_app = Celery(
    "xiantuai",
    broker=broker_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND") or broker_url(),
    include=["app.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
)
