"""
Unit tests for the fetch_news Celery task.
"""

import logging
from unittest.mock import MagicMock, patch

import redis
from django.test import TestCase

from news.schemas import NewsArticle
from news.tasks import fetch_news


class FetchNewsTaskTests(TestCase):
    """Tests for the fetch_news Celery task orchestration."""

    def _make_raw_article(self, title="Gold surges", sentiment_score=0.5):
        return {
            "title": title,
            "source_name": "Reuters",
            "source_url": "https://example.com/article",
            "published_at": "2024-01-15T12:00:00Z",
            "description": "Gold prices rose today.",
            "sentiment_score": sentiment_score,
        }

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_success_stores_articles_and_logs(self, MockClient, MockCache):
        """On success, should sanitize, classify, store, and log count."""
        mock_client = MockClient.return_value
        mock_client.fetch_articles.return_value = [
            self._make_raw_article(title="Gold surges", sentiment_score=0.5),
            self._make_raw_article(title="Gold falls", sentiment_score=-0.5),
        ]
        mock_cache = MockCache.return_value

        with self.assertLogs("news.tasks", level="INFO") as cm:
            fetch_news()

        # Verify store_articles was called with processed NewsArticle objects
        mock_cache.store_articles.assert_called_once()
        stored_articles = mock_cache.store_articles.call_args[0][0]
        self.assertEqual(len(stored_articles), 2)
        self.assertIsInstance(stored_articles[0], NewsArticle)
        self.assertEqual(stored_articles[0].title, "Gold surges")
        self.assertEqual(stored_articles[0].sentiment_label, "positive")
        self.assertEqual(stored_articles[1].sentiment_label, "negative")

        # Verify success log
        self.assertTrue(
            any("successfully fetched and cached 2 articles" in msg for msg in cm.output)
        )

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_empty_response_retains_cache_and_logs_warning(self, MockClient, MockCache):
        """On empty response, should retain previous cache and log warning."""
        mock_client = MockClient.return_value
        mock_client.fetch_articles.return_value = []
        mock_cache = MockCache.return_value

        with self.assertLogs("news.tasks", level="WARNING") as cm:
            fetch_news()

        # store_articles should NOT be called
        mock_cache.store_articles.assert_not_called()

        # Warning should be logged
        self.assertTrue(
            any("empty response" in msg for msg in cm.output)
        )

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_redis_error_on_store_logs_and_discards(self, MockClient, MockCache):
        """On Redis error during store, should log error and discard articles."""
        mock_client = MockClient.return_value
        mock_client.fetch_articles.return_value = [self._make_raw_article()]
        mock_cache = MockCache.return_value
        mock_cache.store_articles.side_effect = redis.RedisError("Connection refused")

        with self.assertLogs("news.tasks", level="ERROR") as cm:
            fetch_news()

        # Error should be logged
        self.assertTrue(
            any("Redis unreachable" in msg for msg in cm.output)
        )

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_sanitizes_html_in_fields(self, MockClient, MockCache):
        """Should sanitize HTML from title, source_name, and description."""
        mock_client = MockClient.return_value
        mock_client.fetch_articles.return_value = [
            {
                "title": "<b>Gold</b> surges<script>alert('x')</script>",
                "source_name": "<em>Reuters</em>",
                "source_url": "https://example.com",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "<p>Gold prices</p> rose.",
                "sentiment_score": 0.0,
            }
        ]
        mock_cache = MockCache.return_value

        fetch_news()

        stored_articles = mock_cache.store_articles.call_args[0][0]
        self.assertEqual(stored_articles[0].title, "Gold surges")
        self.assertEqual(stored_articles[0].source_name, "Reuters")
        self.assertEqual(stored_articles[0].description, "Gold prices rose.")

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_classifies_sentiment_correctly(self, MockClient, MockCache):
        """Should classify sentiment based on score thresholds."""
        mock_client = MockClient.return_value
        mock_client.fetch_articles.return_value = [
            self._make_raw_article(title="Positive", sentiment_score=0.5),
            self._make_raw_article(title="Neutral", sentiment_score=0.0),
            self._make_raw_article(title="Negative", sentiment_score=-0.5),
            self._make_raw_article(title="Boundary pos", sentiment_score=0.2),
            self._make_raw_article(title="Boundary neg", sentiment_score=-0.2),
        ]
        mock_cache = MockCache.return_value

        fetch_news()

        stored = mock_cache.store_articles.call_args[0][0]
        self.assertEqual(stored[0].sentiment_label, "positive")
        self.assertEqual(stored[1].sentiment_label, "neutral")
        self.assertEqual(stored[2].sentiment_label, "negative")
        self.assertEqual(stored[3].sentiment_label, "neutral")  # 0.2 is neutral
        self.assertEqual(stored[4].sentiment_label, "neutral")  # -0.2 is neutral

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_task_is_independent_shared_task(self, MockClient, MockCache):
        """fetch_news should be a Celery shared_task (no autoretry)."""
        # Verify it's registered as a task
        self.assertTrue(hasattr(fetch_news, "delay"))
        self.assertTrue(hasattr(fetch_news, "apply_async"))

    @patch("news.tasks.NewsCacheService")
    @patch("news.tasks.MarketauxClient")
    def test_handles_missing_fields_gracefully(self, MockClient, MockCache):
        """Should handle articles with missing optional fields using defaults."""
        mock_client = MockClient.return_value
        mock_client.fetch_articles.return_value = [
            {
                "title": "Minimal article",
                "source_name": "",
                "source_url": "https://example.com",
                "published_at": "",
                "description": "",
                "sentiment_score": 0.0,
            }
        ]
        mock_cache = MockCache.return_value

        fetch_news()

        stored = mock_cache.store_articles.call_args[0][0]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].title, "Minimal article")
        self.assertEqual(stored[0].source_name, "")
        self.assertEqual(stored[0].sentiment_label, "neutral")
