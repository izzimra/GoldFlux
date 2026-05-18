"""Unit tests for news views."""

from unittest.mock import patch

import redis
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from news.views import NewsListView


class TestNewsListView(TestCase):
    """Tests for GET /api/v1/news/gold/ endpoint."""

    def setUp(self):
        self.factory = APIRequestFactory()
        self.view = NewsListView.as_view()
        self.sample_articles = [
            {
                "title": "Gold Prices Surge",
                "source_name": "Reuters",
                "source_url": "https://reuters.com/article/1",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "Gold futures climbed to a three-week high.",
                "sentiment_score": 0.65,
            },
            {
                "title": "Gold Drops on Strong Dollar",
                "source_name": "Bloomberg",
                "source_url": "https://bloomberg.com/article/2",
                "published_at": "2024-01-15T10:00:00Z",
                "description": "Gold prices fell as the dollar strengthened.",
                "sentiment_score": -0.45,
            },
            {
                "title": "Gold Steady Amid Uncertainty",
                "source_name": "CNBC",
                "source_url": "https://cnbc.com/article/3",
                "published_at": "2024-01-15T08:00:00Z",
                "description": "Gold held steady as markets awaited data.",
                "sentiment_score": 0.1,
            },
        ]
        self.last_updated = "2024-01-15T14:30:00Z"

    @patch("news.views.NewsCacheService")
    def test_returns_articles_ordered_by_published_at_descending(self, mock_cache_cls):
        """Articles should be ordered by published_at descending."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        articles = response.data["articles"]
        self.assertEqual(len(articles), 3)
        # Most recent first
        self.assertEqual(articles[0]["published_at"], "2024-01-15T12:00:00Z")
        self.assertEqual(articles[1]["published_at"], "2024-01-15T10:00:00Z")
        self.assertEqual(articles[2]["published_at"], "2024-01-15T08:00:00Z")

    @patch("news.views.NewsCacheService")
    def test_includes_last_updated_metadata(self, mock_cache_cls):
        """Response should include last_updated field."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["last_updated"], "2024-01-15T14:30:00Z")

    @patch("news.views.NewsCacheService")
    def test_includes_sentiment_label(self, mock_cache_cls):
        """Each article should have a derived sentiment_label."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        articles = response.data["articles"]
        self.assertEqual(articles[0]["sentiment_label"], "positive")  # 0.65
        self.assertEqual(articles[1]["sentiment_label"], "negative")  # -0.45
        self.assertEqual(articles[2]["sentiment_label"], "neutral")  # 0.1

    @patch("news.views.NewsCacheService")
    def test_limit_parameter_restricts_results(self, mock_cache_cls):
        """Limit parameter should restrict the number of articles returned."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/", {"limit": "2"})
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["articles"]), 2)

    @patch("news.views.NewsCacheService")
    def test_default_limit_is_30(self, mock_cache_cls):
        """Without limit param, should return up to 30 articles."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        # We only have 3 articles, so all 3 should be returned
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["articles"]), 3)

    def test_invalid_limit_non_integer_returns_400(self):
        """Non-integer limit should return 400."""
        request = self.factory.get("/api/v1/news/gold/", {"limit": "abc"})
        response = self.view(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("limit", response.data["parameter"])

    def test_invalid_limit_zero_returns_400(self):
        """Limit of 0 should return 400."""
        request = self.factory.get("/api/v1/news/gold/", {"limit": "0"})
        response = self.view(request)

        self.assertEqual(response.status_code, 400)

    def test_invalid_limit_over_30_returns_400(self):
        """Limit over 30 should return 400."""
        request = self.factory.get("/api/v1/news/gold/", {"limit": "31"})
        response = self.view(request)

        self.assertEqual(response.status_code, 400)

    def test_invalid_limit_negative_returns_400(self):
        """Negative limit should return 400."""
        request = self.factory.get("/api/v1/news/gold/", {"limit": "-1"})
        response = self.view(request)

        self.assertEqual(response.status_code, 400)

    @patch("news.views.NewsCacheService")
    def test_empty_cache_returns_empty_array_with_message(self, mock_cache_cls):
        """Empty cache should return empty array with message."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = ([], None)

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["articles"], [])
        self.assertIn("message", response.data)

    @patch("news.views.NewsCacheService")
    def test_redis_unreachable_returns_empty_with_message(self, mock_cache_cls):
        """Redis error should return empty array with unavailable message."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.side_effect = redis.RedisError("Connection refused")

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["articles"], [])
        self.assertEqual(
            response.data["message"], "news is temporarily unavailable"
        )

    @patch("news.views.NewsCacheService")
    def test_all_required_fields_present(self, mock_cache_cls):
        """Each article should have all required fields."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/")
        response = self.view(request)

        required_fields = {
            "title",
            "source_name",
            "source_url",
            "published_at",
            "description",
            "sentiment_score",
            "sentiment_label",
        }
        for article in response.data["articles"]:
            self.assertTrue(
                required_fields.issubset(set(article.keys())),
                f"Missing fields: {required_fields - set(article.keys())}",
            )

    @patch("news.views.NewsCacheService")
    def test_valid_limit_boundary_1(self, mock_cache_cls):
        """Limit of 1 should return exactly 1 article."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/", {"limit": "1"})
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["articles"]), 1)

    @patch("news.views.NewsCacheService")
    def test_valid_limit_boundary_30(self, mock_cache_cls):
        """Limit of 30 should be accepted."""
        mock_cache = mock_cache_cls.return_value
        mock_cache.get_cached_articles.return_value = (
            self.sample_articles,
            self.last_updated,
        )

        request = self.factory.get("/api/v1/news/gold/", {"limit": "30"})
        response = self.view(request)

        self.assertEqual(response.status_code, 200)
