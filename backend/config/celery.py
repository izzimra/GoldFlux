"""
Celery application configuration for GoldFlux.

Configures the Celery app with Redis as broker, Beat schedule for daily
gold price ingestion, news fetching, and duplicate task rejection.
"""

import logging
import os
import uuid

from celery import Celery
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

app.conf.beat_schedule = {
    "ingest-gold-prices-daily": {
        "task": "prices.tasks.ingest_gold_prices",
        "schedule": crontab(hour=INGESTION_HOUR, minute=INGESTION_MINUTE),
        "options": {
            "task_id": INGESTION_TASK_ID,
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
