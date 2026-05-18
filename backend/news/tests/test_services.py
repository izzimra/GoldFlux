"""
Unit tests for news services - HTML sanitization utility.
"""

from django.test import TestCase

from news.services import sanitize_html


class SanitizeHtmlTests(TestCase):
    """Tests for the sanitize_html function."""

    def test_plain_text_unchanged(self):
        """Plain text without HTML should be returned as-is."""
        text = "Gold prices surge amid market uncertainty"
        self.assertEqual(sanitize_html(text), text)

    def test_strips_basic_html_tags(self):
        """Should remove common HTML tags like <p>, <div>, <a>, <b>, etc."""
        text = "<p>Gold <b>prices</b> surge</p>"
        self.assertEqual(sanitize_html(text), "Gold prices surge")

    def test_strips_anchor_tags_keeps_text(self):
        """Should remove <a> tags but keep the link text."""
        text = '<a href="https://example.com">Reuters article</a>'
        self.assertEqual(sanitize_html(text), "Reuters article")

    def test_strips_div_and_span(self):
        """Should remove <div> and <span> tags."""
        text = "<div><span>Market update</span></div>"
        self.assertEqual(sanitize_html(text), "Market update")

    def test_removes_script_tags_and_content(self):
        """Should remove <script> tags AND their content entirely."""
        text = "Hello<script>alert('xss')</script> World"
        self.assertEqual(sanitize_html(text), "Hello World")

    def test_removes_script_with_attributes(self):
        """Should remove <script> tags with attributes."""
        text = 'Before<script type="text/javascript">var x=1;</script>After'
        self.assertEqual(sanitize_html(text), "BeforeAfter")

    def test_removes_style_tags_and_content(self):
        """Should remove <style> tags and their CSS content."""
        text = "Hello<style>.red{color:red}</style> World"
        self.assertEqual(sanitize_html(text), "Hello World")

    def test_handles_nested_tags(self):
        """Should handle nested HTML tags."""
        text = "<div><p><strong>Gold</strong> is <em>rising</em></p></div>"
        self.assertEqual(sanitize_html(text), "Gold is rising")

    def test_handles_empty_string(self):
        """Should return empty string for empty input."""
        self.assertEqual(sanitize_html(""), "")

    def test_handles_none_like_empty(self):
        """Should handle falsy values gracefully."""
        self.assertEqual(sanitize_html(""), "")

    def test_collapses_whitespace(self):
        """Should collapse multiple whitespace characters into single space."""
        text = "<p>Gold</p>   <p>prices</p>"
        self.assertEqual(sanitize_html(text), "Gold prices")

    def test_strips_leading_trailing_whitespace(self):
        """Should strip leading and trailing whitespace from result."""
        text = "  <p>Gold prices</p>  "
        self.assertEqual(sanitize_html(text), "Gold prices")

    def test_case_insensitive_script_removal(self):
        """Should handle SCRIPT tags in any case."""
        text = "Before<SCRIPT>evil()</SCRIPT>After"
        self.assertEqual(sanitize_html(text), "BeforeAfter")

    def test_multiline_script_removal(self):
        """Should remove script blocks spanning multiple lines."""
        text = "Hello<script>\nvar x = 1;\nvar y = 2;\n</script>World"
        self.assertEqual(sanitize_html(text), "HelloWorld")

    def test_self_closing_tags(self):
        """Should handle self-closing tags like <br/> and <img/>."""
        text = "Line one<br/>Line two"
        # <br/> is stripped, text on both sides is concatenated
        self.assertEqual(sanitize_html(text), "Line oneLine two")

    def test_img_tag_removed(self):
        """Should remove <img> tags entirely."""
        text = 'Gold <img src="chart.png" alt="chart"/> prices'
        self.assertEqual(sanitize_html(text), "Gold prices")

    def test_html_entities_preserved(self):
        """HTML entities in text content should be preserved as-is."""
        text = "<p>Gold &amp; Silver</p>"
        self.assertEqual(sanitize_html(text), "Gold & Silver")


class SentimentClassifierTests(TestCase):
    """Unit tests for SentimentClassifier.classify()."""

    def test_positive_score(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(0.5), "positive")

    def test_negative_score(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(-0.5), "negative")

    def test_neutral_score_zero(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(0.0), "neutral")

    def test_boundary_positive_exclusive(self):
        """Score of exactly 0.2 should be neutral (not positive)."""
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(0.2), "neutral")

    def test_boundary_negative_exclusive(self):
        """Score of exactly -0.2 should be neutral (not negative)."""
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(-0.2), "neutral")

    def test_just_above_positive_threshold(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(0.201), "positive")

    def test_just_below_negative_threshold(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(-0.201), "negative")

    def test_extreme_positive(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(1.0), "positive")

    def test_extreme_negative(self):
        from news.services import SentimentClassifier

        self.assertEqual(SentimentClassifier.classify(-1.0), "negative")


# ──────────────────────────────────────────────────────────────────────────────
# NewsCacheService Tests
# ──────────────────────────────────────────────────────────────────────────────

import json
from unittest.mock import MagicMock, patch

from news.schemas import NewsArticle
from news.services import (
    NEWS_CACHE_KEY,
    NEWS_CACHE_TTL,
    NEWS_LAST_UPDATED_KEY,
    NewsCacheService,
)


class TestNewsCacheService(TestCase):
    """Tests for NewsCacheService Redis caching operations."""

    def setUp(self):
        self.patcher = patch("news.services.redis.Redis.from_url")
        self.mock_redis_from_url = self.patcher.start()
        self.mock_client = MagicMock()
        self.mock_redis_from_url.return_value = self.mock_client
        self.service = NewsCacheService()

    def tearDown(self):
        self.patcher.stop()

    def _make_article(self, title="Gold surges", source_name="Reuters"):
        return NewsArticle(
            title=title,
            source_name=source_name,
            source_url="https://example.com/article",
            published_at="2024-01-15T12:00:00Z",
            description="Gold prices rose today.",
            sentiment_score=0.5,
            sentiment_label="positive",
        )

    def test_store_articles_serializes_and_sets_in_redis(self):
        """store_articles should serialize articles to JSON and SET in Redis."""
        mock_pipe = MagicMock()
        self.mock_client.pipeline.return_value = mock_pipe

        articles = [self._make_article(), self._make_article(title="Gold falls")]
        self.service.store_articles(articles)

        # Verify pipeline was used
        self.mock_client.pipeline.assert_called_once()

        # Verify SET calls on pipeline
        calls = mock_pipe.set.call_args_list
        self.assertEqual(len(calls), 2)

        # First call: articles
        articles_call = calls[0]
        self.assertEqual(articles_call[0][0], NEWS_CACHE_KEY)
        stored_data = json.loads(articles_call[0][1])
        self.assertEqual(len(stored_data), 2)
        self.assertEqual(stored_data[0]["title"], "Gold surges")
        self.assertEqual(stored_data[1]["title"], "Gold falls")
        self.assertEqual(articles_call[1]["ex"], NEWS_CACHE_TTL)

        # Second call: last_updated timestamp
        timestamp_call = calls[1]
        self.assertEqual(timestamp_call[0][0], NEWS_LAST_UPDATED_KEY)
        self.assertEqual(timestamp_call[1]["ex"], NEWS_CACHE_TTL)

        # Pipeline executed
        mock_pipe.execute.assert_called_once()

    def test_store_articles_replaces_previous_cache(self):
        """store_articles should replace the entire cached set, not append."""
        mock_pipe = MagicMock()
        self.mock_client.pipeline.return_value = mock_pipe

        # Store first set
        articles_v1 = [self._make_article(title="Article 1")]
        self.service.store_articles(articles_v1)

        # Store second set (should replace, not append)
        mock_pipe.reset_mock()
        articles_v2 = [self._make_article(title="Article 2")]
        self.service.store_articles(articles_v2)

        calls = mock_pipe.set.call_args_list
        stored_data = json.loads(calls[0][0][1])
        self.assertEqual(len(stored_data), 1)
        self.assertEqual(stored_data[0]["title"], "Article 2")

    def test_store_articles_sets_ttl_5_hours(self):
        """store_articles should set TTL of 18000 seconds (5 hours)."""
        mock_pipe = MagicMock()
        self.mock_client.pipeline.return_value = mock_pipe

        self.service.store_articles([self._make_article()])

        for call in mock_pipe.set.call_args_list:
            self.assertEqual(call[1]["ex"], 18000)

    def test_get_cached_articles_returns_articles_and_timestamp(self):
        """get_cached_articles should return deserialized articles and timestamp."""
        articles_data = [
            {
                "title": "Gold surges",
                "source_name": "Reuters",
                "source_url": "https://example.com",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "Gold prices rose.",
                "sentiment_score": 0.5,
                "sentiment_label": "positive",
            }
        ]
        last_updated = "2024-01-15T14:30:00+00:00"

        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [json.dumps(articles_data), last_updated]
        self.mock_client.pipeline.return_value = mock_pipe

        articles, timestamp = self.service.get_cached_articles()

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Gold surges")
        self.assertEqual(timestamp, last_updated)

    def test_get_cached_articles_returns_empty_when_cache_miss(self):
        """get_cached_articles should return ([], None) when cache is empty."""
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [None, None]
        self.mock_client.pipeline.return_value = mock_pipe

        articles, timestamp = self.service.get_cached_articles()

        self.assertEqual(articles, [])
        self.assertIsNone(timestamp)

    def test_get_cached_articles_handles_invalid_json(self):
        """get_cached_articles should return ([], None) for corrupted cache data."""
        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = ["not valid json{{{", "2024-01-15T14:30:00Z"]
        self.mock_client.pipeline.return_value = mock_pipe

        articles, timestamp = self.service.get_cached_articles()

        self.assertEqual(articles, [])
        self.assertIsNone(timestamp)

    def test_store_articles_stores_last_updated_as_iso_timestamp(self):
        """store_articles should store an ISO 8601 timestamp for last_updated."""
        mock_pipe = MagicMock()
        self.mock_client.pipeline.return_value = mock_pipe

        self.service.store_articles([self._make_article()])

        calls = mock_pipe.set.call_args_list
        timestamp_value = calls[1][0][1]
        # Should be parseable as ISO 8601
        from datetime import datetime

        parsed = datetime.fromisoformat(timestamp_value)
        self.assertIsNotNone(parsed)
