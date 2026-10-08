from __future__ import annotations

from .celery_app import celery_app


@celery_app.task(bind=True, name="xiantu.run_generation_pipeline", max_retries=2, acks_late=True)
def run_generation_task(self, generation_id: str, product_id: str, options: dict[str, str]) -> None:
    # Import lazily to keep the API module importable without starting a worker.
    from .main import run_generation_pipeline

    run_generation_pipeline(generation_id, product_id, options)
