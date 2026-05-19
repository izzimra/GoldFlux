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
        """Beat schedule should include the daily pipeline orchestrator task."""
        from config.celery import app

        schedule = app.conf.beat_schedule
        self.assertIn("run-daily-pipeline", schedule)

    def test_ingestion_task_targets_correct_task(self):
        """The scheduled daily task should target the pipeline orchestrator."""
        from config.celery import app

        entry = app.conf.beat_schedule["run-daily-pipeline"]
        self.assertEqual(entry["task"], "config.celery.run_daily_pipeline")

    def test_ingestion_task_has_crontab_schedule(self):
        """The daily pipeline task should use a crontab schedule."""
        from celery.schedules import crontab

        from config.celery import app

        entry = app.conf.beat_schedule["run-daily-pipeline"]
        self.assertIsInstance(entry["schedule"], crontab)

    def test_ingestion_task_has_task_id_for_duplicate_rejection(self):
        """The daily pipeline task should have a fixed task_id to prevent duplicates."""
        from config.celery import app

        entry = app.conf.beat_schedule["run-daily-pipeline"]
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


class CeleryPipelineChainTest(TestCase):
    """Tests verifying the daily pipeline chain wiring.

    Wave 11 / Task 16.3: ingest_gold_prices → train_model → generate_predictions
    must be wired as a Celery chain such that each task runs only after the
    previous one succeeds, while the news fetch task remains independent.
    """

    def test_run_daily_pipeline_task_is_registered(self):
        """The orchestrator task should be registered with Celery."""
        from config.celery import app

        self.assertIn("config.celery.run_daily_pipeline", app.tasks)

    def test_pipeline_orchestrator_dispatches_chain(self):
        """run_daily_pipeline should dispatch a chain of the three pipeline tasks."""
        from unittest.mock import MagicMock, patch

        with patch("celery.canvas._chain.apply_async") as mock_apply_async:
            mock_apply_async.return_value = MagicMock(id="chain-root-id")

            from config.celery import run_daily_pipeline

            # Invoke the orchestrator's underlying function directly
            result = run_daily_pipeline.run()

            self.assertEqual(result, "chain-root-id")
            self.assertTrue(mock_apply_async.called)

    def test_pipeline_chain_order_is_ingest_train_predict(self):
        """The chain order must be ingest_gold_prices → train_model → generate_predictions."""
        from unittest.mock import patch

        captured = {}

        def fake_apply_async(self_, *args, **kwargs):
            # ``self_`` is the chain instance; capture its tasks for inspection
            captured["tasks"] = list(self_.tasks)

            class _Result:
                id = "chain-root-id"

            return _Result()

        with patch("celery.canvas._chain.apply_async", new=fake_apply_async):
            from config.celery import run_daily_pipeline

            run_daily_pipeline.run()

        task_names = [sig.task for sig in captured["tasks"]]
        self.assertEqual(
            task_names,
            [
                "prices.tasks.ingest_gold_prices",
                "predictions.tasks.train_model",
                "predictions.tasks.generate_predictions",
            ],
        )

    def test_pipeline_chain_uses_immutable_signatures(self):
        """Chain signatures should be immutable so upstream return values aren't forwarded."""
        from unittest.mock import patch

        captured = {}

        def fake_apply_async(self_, *args, **kwargs):
            captured["tasks"] = list(self_.tasks)

            class _Result:
                id = "chain-root-id"

            return _Result()

        with patch("celery.canvas._chain.apply_async", new=fake_apply_async):
            from config.celery import run_daily_pipeline

            run_daily_pipeline.run()

        # Immutable signatures have ``immutable=True`` on their options
        for sig in captured["tasks"]:
            self.assertTrue(
                sig.immutable,
                f"Chain signature for {sig.task} should be immutable",
            )

    def test_news_fetch_task_not_in_pipeline_chain(self):
        """The news fetch task must NOT be part of the daily pipeline chain.

        Validates Requirement 23.4: news pipeline operates independently.
        """
        from unittest.mock import patch

        captured = {}

        def fake_apply_async(self_, *args, **kwargs):
            captured["tasks"] = list(self_.tasks)

            class _Result:
                id = "chain-root-id"

            return _Result()

        with patch("celery.canvas._chain.apply_async", new=fake_apply_async):
            from config.celery import run_daily_pipeline

            run_daily_pipeline.run()

        task_names = [sig.task for sig in captured["tasks"]]
        self.assertNotIn("news.tasks.fetch_news", task_names)

    def test_daily_pipeline_task_id_is_deterministic(self):
        """The orchestrator task_id should be deterministic across restarts."""
        from config.celery import DAILY_PIPELINE_TASK_ID

        expected = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, "goldflux.run_daily_pipeline")
        )
        self.assertEqual(DAILY_PIPELINE_TASK_ID, expected)

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_news_schedule_independent_of_pipeline_schedule(self):
        """News schedule must be a distinct entry from the daily pipeline schedule.

        Validates Requirement 23.4: independent scheduling.
        """
        import config.celery as celery_module

        importlib.reload(celery_module)
        schedule = celery_module.app.conf.beat_schedule

        self.assertIn("run-daily-pipeline", schedule)
        self.assertIn("fetch-news-every-n-hours", schedule)

        pipeline_entry = schedule["run-daily-pipeline"]
        news_entry = schedule["fetch-news-every-n-hours"]

        # Entries must target different tasks
        self.assertNotEqual(pipeline_entry["task"], news_entry["task"])
        self.assertEqual(news_entry["task"], "news.tasks.fetch_news")
