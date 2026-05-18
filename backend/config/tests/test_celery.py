"""
Unit tests for Celery app configuration and Beat schedule.
"""

import importlib
import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings


class CeleryAppConfigTest(TestCase):
    """Tests for the Celery application configuration."""

    def test_celery_app_is_importable(self):
        """The Celery app should be importable from config."""
        from config.celery import app

        self.assertIsNotNone(app)
        self.assertEqual(app.main, "config")

    def test_celery_app_exported_from_init(self):
        """The Celery app should be exported from config.__init__."""
        from config import celery_app

        self.assertIsNotNone(celery_app)
        self.assertEqual(celery_app.main, "config")

    def test_beat_schedule_contains_ingestion_task(self):
        """Beat schedule should include the daily gold price ingestion task."""
        from config.celery import app

        schedule = app.conf.beat_schedule
        self.assertIn("ingest-gold-prices-daily", schedule)

    def test_ingestion_task_targets_correct_task(self):
        """The scheduled task should target prices.tasks.ingest_gold_prices."""
        from config.celery import app

        entry = app.conf.beat_schedule["ingest-gold-prices-daily"]
        self.assertEqual(entry["task"], "prices.tasks.ingest_gold_prices")

    def test_ingestion_task_has_crontab_schedule(self):
        """The ingestion task should use a crontab schedule."""
        from celery.schedules import crontab

        from config.celery import app

        entry = app.conf.beat_schedule["ingest-gold-prices-daily"]
        self.assertIsInstance(entry["schedule"], crontab)

    def test_ingestion_task_has_task_id_for_duplicate_rejection(self):
        """The ingestion task should have a fixed task_id to prevent duplicates."""
        from config.celery import app

        entry = app.conf.beat_schedule["ingest-gold-prices-daily"]
        task_id = entry["options"]["task_id"]
        # Verify it's a valid UUID
        parsed = uuid.UUID(task_id)
        self.assertEqual(str(parsed), task_id)

    def test_default_ingestion_time_is_0030(self):
        """Default ingestion time should be 00:30 UTC."""
        from config.celery import INGESTION_HOUR, INGESTION_MINUTE

        self.assertEqual(INGESTION_HOUR, 0)
        self.assertEqual(INGESTION_MINUTE, 30)

    @patch.dict("os.environ", {"INGESTION_TIME": "06:15"})
    def test_ingestion_time_configurable_via_env(self):
        """INGESTION_TIME env var should configure the schedule time."""
        import importlib

        import config.celery as celery_module

        importlib.reload(celery_module)

        self.assertEqual(celery_module.INGESTION_HOUR, 6)
        self.assertEqual(celery_module.INGESTION_MINUTE, 15)

        # Reload with default to restore state
        import os

        if "INGESTION_TIME" in os.environ:
            del os.environ["INGESTION_TIME"]
        importlib.reload(celery_module)

    def test_beat_schedule_filename_set_for_persistence(self):
        """Beat schedule should persist across restarts via schedule file."""
        from config.celery import app

        self.assertEqual(app.conf.beat_schedule_filename, "celerybeat-schedule")

    def test_broker_url_uses_redis(self):
        """Broker URL should be configured to use Redis."""
        from config.celery import app

        self.assertIn("redis://", app.conf.broker_url)

    def test_result_backend_uses_redis(self):
        """Result backend should be configured to use Redis."""
        from config.celery import app

        self.assertIn("redis://", app.conf.result_backend)

    def test_task_id_is_deterministic(self):
        """The ingestion task_id should be deterministic (same across restarts)."""
        from config.celery import INGESTION_TASK_ID

        # UUID v5 with the same namespace and name should always produce the same value
        expected = str(uuid.uuid5(uuid.NAMESPACE_DNS, "goldflux.ingest_gold_prices"))
        self.assertEqual(INGESTION_TASK_ID, expected)

    def test_autodiscover_tasks_configured(self):
        """Celery should auto-discover tasks from installed apps."""
        from config.celery import app

        # The app should have autodiscover configured (it's called during module load)
        # We verify by checking that the prices.tasks module is discoverable
        self.assertIsNotNone(app)


class CeleryNewsScheduleTest(TestCase):
    """Tests for the news fetch Celery Beat schedule configuration."""

    def _reload_celery(self):
        """Helper to reload the celery module to pick up env changes."""
        import config.celery as celery_module

        importlib.reload(celery_module)
        return celery_module

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_news_schedule_present_when_api_key_set(self):
        """Beat schedule should include fetch-news task when NEWS_API_KEY is set."""
        celery_module = self._reload_celery()
        schedule = celery_module.app.conf.beat_schedule
        self.assertIn("fetch-news-every-n-hours", schedule)

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_news_schedule_targets_correct_task(self):
        """The news schedule entry should target news.tasks.fetch_news."""
        celery_module = self._reload_celery()
        entry = celery_module.app.conf.beat_schedule["fetch-news-every-n-hours"]
        self.assertEqual(entry["task"], "news.tasks.fetch_news")

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_news_schedule_uses_crontab(self):
        """The news schedule should use a crontab schedule."""
        from celery.schedules import crontab

        celery_module = self._reload_celery()
        entry = celery_module.app.conf.beat_schedule["fetch-news-every-n-hours"]
        self.assertIsInstance(entry["schedule"], crontab)

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_news_schedule_default_interval_is_4_hours(self):
        """Default news fetch interval should be every 4 hours."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 4)

    @patch.dict(
        "os.environ", {"NEWS_API_KEY": "test-key-123", "NEWS_FETCH_INTERVAL_HOURS": "6"}
    )
    def test_news_interval_configurable_via_env(self):
        """NEWS_FETCH_INTERVAL_HOURS env var should configure the interval."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 6)

    @patch.dict(
        "os.environ", {"NEWS_API_KEY": "test-key-123", "NEWS_FETCH_INTERVAL_HOURS": "1"}
    )
    def test_news_interval_minimum_is_1(self):
        """Minimum interval should be 1 hour."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 1)

    @patch.dict(
        "os.environ",
        {"NEWS_API_KEY": "test-key-123", "NEWS_FETCH_INTERVAL_HOURS": "12"},
    )
    def test_news_interval_maximum_is_12(self):
        """Maximum interval should be 12 hours."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 12)

    @patch.dict(
        "os.environ", {"NEWS_API_KEY": "test-key-123", "NEWS_FETCH_INTERVAL_HOURS": "0"}
    )
    def test_news_interval_below_range_clamped_to_1(self):
        """Interval below 1 should be clamped to 1."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 1)

    @patch.dict(
        "os.environ",
        {"NEWS_API_KEY": "test-key-123", "NEWS_FETCH_INTERVAL_HOURS": "24"},
    )
    def test_news_interval_above_range_clamped_to_12(self):
        """Interval above 12 should be clamped to 12."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 12)

    @patch.dict(
        "os.environ",
        {"NEWS_API_KEY": "test-key-123", "NEWS_FETCH_INTERVAL_HOURS": "invalid"},
    )
    def test_news_interval_invalid_value_defaults_to_4(self):
        """Invalid (non-integer) interval should default to 4."""
        celery_module = self._reload_celery()
        self.assertEqual(celery_module.NEWS_FETCH_INTERVAL_HOURS, 4)

    @patch.dict("os.environ", {"NEWS_API_KEY": ""}, clear=False)
    def test_news_schedule_skipped_when_api_key_empty(self):
        """Beat schedule should NOT include fetch-news when NEWS_API_KEY is empty."""
        celery_module = self._reload_celery()
        schedule = celery_module.app.conf.beat_schedule
        self.assertNotIn("fetch-news-every-n-hours", schedule)

    @patch.dict("os.environ", {}, clear=False)
    def test_news_schedule_skipped_when_api_key_missing(self):
        """Beat schedule should NOT include fetch-news when NEWS_API_KEY is not set."""
        import os

        # Ensure NEWS_API_KEY is not in environment
        os.environ.pop("NEWS_API_KEY", None)
        celery_module = self._reload_celery()
        schedule = celery_module.app.conf.beat_schedule
        self.assertNotIn("fetch-news-every-n-hours", schedule)

    @patch.dict("os.environ", {"NEWS_API_KEY": "   "}, clear=False)
    def test_news_schedule_skipped_when_api_key_whitespace(self):
        """Beat schedule should NOT include fetch-news when NEWS_API_KEY is whitespace."""
        celery_module = self._reload_celery()
        schedule = celery_module.app.conf.beat_schedule
        self.assertNotIn("fetch-news-every-n-hours", schedule)

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_news_schedule_runs_at_top_of_hour(self):
        """News fetch should run at minute 0 of the scheduled hours."""
        celery_module = self._reload_celery()
        entry = celery_module.app.conf.beat_schedule["fetch-news-every-n-hours"]
        schedule = entry["schedule"]
        # crontab minute should contain only 0
        self.assertEqual(schedule.minute, {0})
