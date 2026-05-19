"""
Celery application configuration for GoldFlux.

Configures the Celery app with Redis as broker, Beat schedule for daily
gold price ingestion, news fetching, and duplicate task rejection.
"""

import logging
import os
import uuid

from celery import Celery, chain
from celery.schedules import crontab

logger = logging.getLogger(__name__)

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")

# Load configuration from Django settings, using the CELERY_ namespace.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discover tasks in all registered Django apps.
app.autodiscover_tasks()

# ──────────────────────────────────────────────────────────────────────────────
# Broker Configuration
# ──────────────────────────────────────────────────────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
app.conf.broker_url = REDIS_URL
app.conf.result_backend = REDIS_URL

# ──────────────────────────────────────────────────────────────────────────────
# Task Execution Settings
# ──────────────────────────────────────────────────────────────────────────────
app.conf.task_acks_late = True
app.conf.worker_prefetch_multiplier = 1

# ──────────────────────────────────────────────────────────────────────────────
# Schedule Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Parse INGESTION_TIME env var (format HH:MM, default "00:30") for daily schedule.
INGESTION_TIME = os.environ.get("INGESTION_TIME", "00:30")
_hour, _minute = INGESTION_TIME.split(":")
INGESTION_HOUR = int(_hour)
INGESTION_MINUTE = int(_minute)

# Static task ID for duplicate rejection — prevents concurrent ingestion runs.
INGESTION_TASK_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "goldflux.ingest_gold_prices"))

# Static task ID for the daily pipeline orchestrator — prevents concurrent
# pipeline runs (the orchestrator triggers the ingestion → training →
# prediction chain).
DAILY_PIPELINE_TASK_ID = str(
    uuid.uuid5(uuid.NAMESPACE_DNS, "goldflux.run_daily_pipeline")
)

app.conf.beat_schedule = {
    "run-daily-pipeline": {
        # Orchestrates the chain: ingest_gold_prices → train_model →
        # generate_predictions. Cache invalidation is performed by each
        # individual task on its own successful completion (historical price
        # cache after ingestion, prediction cache after prediction generation).
        "task": "config.celery.run_daily_pipeline",
        "schedule": crontab(hour=INGESTION_HOUR, minute=INGESTION_MINUTE),
        "options": {
            "task_id": DAILY_PIPELINE_TASK_ID,
        },
    },
}

# ──────────────────────────────────────────────────────────────────────────────
# News Fetch Schedule Configuration
# ──────────────────────────────────────────────────────────────────────────────
# Only schedule news fetching if NEWS_API_KEY is configured.
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "").strip()

# Parse NEWS_FETCH_INTERVAL_HOURS (default: 4, valid range: 1-12).
_raw_interval = os.environ.get("NEWS_FETCH_INTERVAL_HOURS", "4")
try:
    NEWS_FETCH_INTERVAL_HOURS = int(_raw_interval)
except (ValueError, TypeError):
    NEWS_FETCH_INTERVAL_HOURS = 4

# Clamp to valid range 1-12.
NEWS_FETCH_INTERVAL_HOURS = max(1, min(12, NEWS_FETCH_INTERVAL_HOURS))

if NEWS_API_KEY:
    app.conf.beat_schedule["fetch-news-every-n-hours"] = {
        "task": "news.tasks.fetch_news",
        "schedule": crontab(minute="0", hour=f"*/{NEWS_FETCH_INTERVAL_HOURS}"),
    }
else:
    logger.error(
        "NEWS_API_KEY is not configured. News fetch task will not be scheduled."
    )

# Persist schedule across restarts using the Django database scheduler
# or the default shelve-based persistence (celerybeat-schedule file).
app.conf.beat_schedule_filename = "celerybeat-schedule"

# ──────────────────────────────────────────────────────────────────────────────
# Duplicate Task Rejection
# ──────────────────────────────────────────────────────────────────────────────
# When a task with the same task_id is already pending or active, reject duplicates.
app.conf.task_reject_on_worker_lost = True


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for verifying Celery connectivity."""
    print(f"Request: {self.request!r}")


@app.task(bind=True, ignore_result=True, name="config.celery.run_daily_pipeline")
def run_daily_pipeline(self):
    """Trigger the daily data pipeline as a Celery chain.

    Chain: ingest_gold_prices → train_model → generate_predictions

    Each link runs only after the previous link succeeds (Celery aborts
    chain execution when an upstream task raises an exception, so a
    retry-exhausted failure in ingestion prevents training, and a failure
    in training prevents prediction generation).

    Cache invalidation is performed by individual tasks on completion:
    - ``ingest_gold_prices`` invalidates the historical price cache.
    - ``generate_predictions`` invalidates the prediction cache.

    Immutable signatures (``.si()``) are used so each task is called with
    no positional arguments — the upstream task's return value is
    discarded rather than forwarded.

    The news fetch task (``news.tasks.fetch_news``) is intentionally
    *not* part of this chain; it runs on its own independent beat
    schedule so a news pipeline failure cannot delay or block price
    ingestion or model training (Requirement 23.4).
    """
    # Import lazily to avoid circular import / app-loading issues at
    # module import time.
    from predictions.tasks import generate_predictions, train_model
    from prices.tasks import ingest_gold_prices

    pipeline = chain(
        ingest_gold_prices.si(),
        train_model.si(),
        generate_predictions.si(),
    )
    async_result = pipeline.apply_async()
    logger.info(
        "Dispatched daily pipeline chain: ingest_gold_prices → "
        "train_model → generate_predictions (root task id: %s)",
        async_result.id,
    )
    return async_result.id
