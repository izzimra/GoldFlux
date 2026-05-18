"""
Unit tests for MarketauxClient service.
"""

import json
from unittest.mock import patch, MagicMock

from django.test import TestCase

from news.services import MarketauxClient


class MarketauxClientConfigTests(TestCase):
    """Tests for MarketauxClient configuration and initialization."""

    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key-123"})
    def test_is_configured_with_key(self):
        """Should return True when NEWS_API_KEY is set."""
        client = MarketauxClient()
        self.assertTrue(client.is_configured())

    @patch.dict("os.environ", {"NEWS_API_KEY": ""}, clear=False)
    def test_is_not_configured_empty_key(self):
        """Should return False and log error when NEWS_API_KEY is empty."""
        client = MarketauxClient()
        self.assertFalse(client.is_configured())

    @patch.dict("os.environ", {}, clear=True)
    def test_is_not_configured_missing_key(self):
        """Should return False when NEWS_API_KEY is not set."""
        client = MarketauxClient()
        self.assertFalse(client.is_configured())

    @patch.dict(
        "os.environ",
        {
            "NEWS_API_BASE_URL": "https://custom.api.com",
            "NEWS_API_KEY": "my-key",
            "NEWS_API_KEYWORDS": "silver,platinum",
        },
    )
    def test_reads_config_from_environment(self):
        """Should read all config from environment variables."""
        client = MarketauxClient()
        self.assertEqual(client.base_url, "https://custom.api.com")
        self.assertEqual(client.api_key, "my-key")
        self.assertEqual(client.keywords, "silver,platinum")

    @patch.dict("os.environ", {"NEWS_API_KEY": "key"}, clear=True)
    def test_uses_defaults_when_env_not_set(self):
        """Should use default values when optional env vars are not set."""
        client = MarketauxClient()
        self.assertEqual(client.base_url, "https://api.marketaux.com")
        self.assertEqual(client.keywords, "gold,XAU,commodities")


class MarketauxClientFetchTests(TestCase):
    """Tests for MarketauxClient.fetch_articles() method."""

    def _make_client(self):
        with patch.dict(
            "os.environ",
            {"NEWS_API_KEY": "test-key", "NEWS_API_BASE_URL": "https://api.marketaux.com"},
        ):
            return MarketauxClient()

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_success(self, mock_get):
        """Should parse a valid Marketaux response and return article dicts."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "title": "Gold Surges",
                    "url": "https://example.com/article1",
                    "source": "Reuters",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": "Gold prices climbed to a three-week high.",
                    "entities": [
                        {"sentiment_score": 0.65}
                    ],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Gold Surges")
        self.assertEqual(articles[0]["source_name"], "Reuters")
        self.assertEqual(articles[0]["source_url"], "https://example.com/article1")
        self.assertEqual(articles[0]["published_at"], "2024-01-15T12:00:00Z")
        self.assertEqual(articles[0]["description"], "Gold prices climbed to a three-week high.")
        self.assertAlmostEqual(articles[0]["sentiment_score"], 0.65)

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_default_sentiment_empty_entities(self, mock_get):
        """Should assign 0.0 sentiment when entities array is empty."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "title": "Gold News",
                    "url": "https://example.com/article",
                    "source": "BBC",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": "Some description",
                    "entities": [],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["sentiment_score"], 0.0)

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_default_sentiment_missing_score(self, mock_get):
        """Should assign 0.0 sentiment when entities exist but score is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "title": "Gold News",
                    "url": "https://example.com/article",
                    "source": "BBC",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": "Some description",
                    "entities": [{"name": "gold", "type": "commodity"}],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["sentiment_score"], 0.0)

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_skips_missing_title(self, mock_get):
        """Should skip articles missing the title field."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "url": "https://example.com/article",
                    "source": "BBC",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": "No title article",
                    "entities": [],
                },
                {
                    "title": "Valid Article",
                    "url": "https://example.com/valid",
                    "source": "CNN",
                    "published_at": "2024-01-15T13:00:00Z",
                    "description": "Has title",
                    "entities": [],
                },
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Valid Article")

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_skips_missing_url(self, mock_get):
        """Should skip articles missing the url field."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "title": "No URL Article",
                    "source": "BBC",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": "Missing url",
                    "entities": [],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 0)

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_truncates_description(self, mock_get):
        """Should truncate description to 300 characters."""
        long_desc = "A" * 500
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "title": "Article",
                    "url": "https://example.com/article",
                    "source": "Reuters",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": long_desc,
                    "entities": [],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles[0]["description"]), 300)

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_malformed_json(self, mock_get):
        """Should return empty list and log error on malformed JSON."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("err", "doc", 0)
        mock_response.text = "not valid json at all" * 30
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(articles, [])

    @patch("news.services.requests.get")
    @patch("news.services.time.sleep")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_retries_on_http_error(self, mock_sleep, mock_get):
        """Should retry with exponential backoff on HTTP errors."""
        import requests as req

        mock_response_fail = MagicMock()
        mock_response_fail.raise_for_status.side_effect = req.exceptions.HTTPError("503")

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "data": [
                {
                    "title": "Success",
                    "url": "https://example.com/ok",
                    "source": "AP",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": "Recovered",
                    "entities": [],
                }
            ]
        }
        mock_response_success.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_response_fail, mock_response_success]

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Success")
        # Should have slept once with 5s backoff
        mock_sleep.assert_called_once_with(5)

    @patch("news.services.requests.get")
    @patch("news.services.time.sleep")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_all_retries_exhausted(self, mock_sleep, mock_get):
        """Should return empty list when all retries are exhausted."""
        import requests as req

        mock_get.side_effect = req.exceptions.ConnectionError("Connection refused")

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(articles, [])
        # Should have slept twice (between attempt 1-2 and 2-3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_sends_correct_params(self, mock_get):
        """Should send correct query parameters to the API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        client.fetch_articles()

        mock_get.assert_called_once_with(
            "https://api.marketaux.com/v1/news/all",
            params={"api_token": "test-key", "search": "gold", "limit": 30},
            timeout=30,
        )

    @patch("news.services.requests.get")
    @patch.dict("os.environ", {"NEWS_API_KEY": "test-key", "NEWS_API_KEYWORDS": "gold"})
    def test_fetch_articles_handles_null_description(self, mock_get):
        """Should handle None description gracefully."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {
                    "title": "Article",
                    "url": "https://example.com/article",
                    "source": "Reuters",
                    "published_at": "2024-01-15T12:00:00Z",
                    "description": None,
                    "entities": [],
                }
            ]
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        client = self._make_client()
        articles = client.fetch_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["description"], "")
