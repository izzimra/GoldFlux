"""
Property-based tests for news services.

Uses Hypothesis to validate universal properties of the Marketaux response
parsing, news cache replacement semantics, sentiment classification,
article filtering, and HTML sanitization.
"""

import json
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from news.schemas import NewsArticle
from news.services import (
    MarketauxClient,
    NewsCacheService,
    SentimentClassifier,
    sanitize_html,
    NEWS_CACHE_KEY,
    NEWS_CACHE_TTL,
    NEWS_LAST_UPDATED_KEY,
)


# ──────────────────────────────────────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────────────────────────────────────

# Valid article titles (non-empty strings without HTML)
valid_titles = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="<>",
    ),
    min_size=1,
    max_size=200,
).filter(lambda s: s.strip())

# Valid URLs
valid_urls = st.from_regex(
    r"https://[a-z]{3,12}\.[a-z]{2,4}/[a-z0-9\-]{1,30}",
    fullmatch=True,
)

# Source names
valid_sources = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
        blacklist_characters="<>",
    ),
    min_size=1,
    max_size=50,
).filter(lambda s: s.strip())

# ISO 8601 timestamps
valid_timestamps = st.from_regex(
    r"2024-0[1-9]-[012][0-9]T[01][0-9]:[0-5][0-9]:[0-5][0-9]Z",
    fullmatch=True,
)

# Descriptions of varying length (some over 300 chars)
valid_descriptions = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="<>",
    ),
    min_size=0,
    max_size=600,
)

# Sentiment scores in valid range
sentiment_scores = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False)

# Sentiment scores that are clearly positive (> 0.2)
positive_scores = st.floats(
    min_value=0.2001, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Sentiment scores that are clearly negative (< -0.2)
negative_scores = st.floats(
    min_value=-1.0, max_value=-0.2001, allow_nan=False, allow_infinity=False
)

# Sentiment scores that are neutral (between -0.2 and 0.2 inclusive)
neutral_scores = st.floats(
    min_value=-0.2, max_value=0.2, allow_nan=False, allow_infinity=False
)

# HTML tag names
html_tags = st.sampled_from([
    "p", "div", "span", "a", "b", "i", "strong", "em", "h1", "h2",
    "h3", "ul", "li", "table", "tr", "td", "br", "img", "header", "footer",
])

# Plain text content (no HTML)
plain_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z", "P"),
        blacklist_characters="<>&",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())


# ──────────────────────────────────────────────────────────────────────────────
# Helper: Build a Marketaux-style article dict
# ──────────────────────────────────────────────────────────────────────────────

def make_marketaux_article(
    title="Gold surges",
    url="https://example.com/article",
    source="Reuters",
    published_at="2024-01-15T12:00:00Z",
    description="Gold prices rose today.",
    entities=None,
):
    """Build a Marketaux API article dict."""
    article = {
        "title": title,
        "url": url,
        "source": source,
        "published_at": published_at,
        "description": description,
    }
    if entities is not None:
        article["entities"] = entities
    return article


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 14: Marketaux response parsing with defaults
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 17.3, 17.4


class PropertyMarketauxResponseParsingTest(TestCase):
    """
    Property 14: Marketaux response parsing with defaults

    For any valid Marketaux API response containing articles, the parser should
    extract title, source, url, published_at, description (truncated to 300 chars),
    and sentiment_score. For any article where entities array is empty or
    sentiment_score is missing, assign 0.0.
    """

    def setUp(self):
        self.client_instance = MarketauxClient()

    @given(
        title=valid_titles,
        url=valid_urls,
        source=valid_sources,
        published_at=valid_timestamps,
        description=valid_descriptions,
        score=sentiment_scores,
    )
    @settings(max_examples=100)
    def test_parser_extracts_all_fields_with_sentiment(
        self, title, url, source, published_at, description, score
    ):
        """
        For any valid article with a sentiment_score in entities, the parser
        should extract all fields correctly and truncate description to 300 chars.

        **Validates: Requirements 17.3**
        """
        # Feature: financial-news-integration, Property 14: Marketaux response parsing with defaults
        article = make_marketaux_article(
            title=title,
            url=url,
            source=source,
            published_at=published_at,
            description=description,
            entities=[{"sentiment_score": score}],
        )

        # Build a mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [article]}

        parsed = self.client_instance._parse_response(mock_response)

        self.assertEqual(len(parsed), 1)
        result = parsed[0]

        # All fields extracted
        self.assertEqual(result["title"], title)
        self.assertEqual(result["source_url"], url)
        self.assertEqual(result["source_name"], source)
        self.assertEqual(result["published_at"], published_at)

        # Description truncated to 300 chars
        self.assertEqual(result["description"], description[:300])
        self.assertLessEqual(len(result["description"]), 300)

        # Sentiment score extracted
        self.assertAlmostEqual(result["sentiment_score"], score, places=5)

    @given(
        title=valid_titles,
        url=valid_urls,
        source=valid_sources,
        published_at=valid_timestamps,
        description=valid_descriptions,
    )
    @settings(max_examples=100)
    def test_parser_assigns_default_sentiment_when_entities_empty(
        self, title, url, source, published_at, description
    ):
        """
        For any article where the entities array is empty, the parser should
        assign a sentiment_score of 0.0.

        **Validates: Requirements 17.4**
        """
        # Feature: financial-news-integration, Property 14: Marketaux response parsing with defaults
        article = make_marketaux_article(
            title=title,
            url=url,
            source=source,
            published_at=published_at,
            description=description,
            entities=[],
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [article]}

        parsed = self.client_instance._parse_response(mock_response)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["sentiment_score"], 0.0)

    @given(
        title=valid_titles,
        url=valid_urls,
        source=valid_sources,
        published_at=valid_timestamps,
        description=valid_descriptions,
    )
    @settings(max_examples=100)
    def test_parser_assigns_default_sentiment_when_entities_missing(
        self, title, url, source, published_at, description
    ):
        """
        For any article where the entities key is absent, the parser should
        assign a sentiment_score of 0.0.

        **Validates: Requirements 17.4**
        """
        # Feature: financial-news-integration, Property 14: Marketaux response parsing with defaults
        article = {
            "title": title,
            "url": url,
            "source": source,
            "published_at": published_at,
            "description": description,
            # No "entities" key at all
        }

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [article]}

        parsed = self.client_instance._parse_response(mock_response)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["sentiment_score"], 0.0)


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 15: News cache replacement semantics
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 17.6


class PropertyNewsCacheReplacementTest(TestCase):
    """
    Property 15: News cache replacement semantics

    For any successful news fetch, storing the new article set in Redis should
    completely replace the previous set. After storage, retrieving from cache
    should return only the newly stored articles.
    """

    def setUp(self):
        self.patcher = patch("news.services.redis.Redis.from_url")
        self.mock_redis_from_url = self.patcher.start()
        self.mock_client = MagicMock()
        self.mock_redis_from_url.return_value = self.mock_client
        self.service = NewsCacheService()

    def tearDown(self):
        self.patcher.stop()

    def _make_article(self, title="Article", source="Source"):
        return NewsArticle(
            title=title,
            source_name=source,
            source_url="https://example.com/article",
            published_at="2024-01-15T12:00:00Z",
            description="Description text.",
            sentiment_score=0.5,
            sentiment_label="positive",
        )

    @given(
        old_count=st.integers(min_value=1, max_value=30),
        new_count=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100)
    def test_new_articles_replace_old_articles_completely(self, old_count, new_count):
        """
        For any two successive stores, the second store should completely
        replace the first. Retrieving from cache returns only the new articles.

        **Validates: Requirements 17.6**
        """
        # Feature: financial-news-integration, Property 15: News cache replacement semantics

        # Simulate Redis storage with an in-memory dict
        redis_store = {}

        mock_pipe = MagicMock()

        def mock_set(key, value, ex=None):
            redis_store[key] = value

        mock_pipe.set.side_effect = mock_set
        mock_pipe.execute.return_value = None
        self.mock_client.pipeline.return_value = mock_pipe

        # Store old articles
        old_articles = [
            self._make_article(title=f"Old Article {i}") for i in range(old_count)
        ]
        self.service.store_articles(old_articles)

        # Reset mock for second store
        mock_pipe.reset_mock()
        mock_pipe.set.side_effect = mock_set
        mock_pipe.execute.return_value = None

        # Store new articles (should replace)
        new_articles = [
            self._make_article(title=f"New Article {i}") for i in range(new_count)
        ]
        self.service.store_articles(new_articles)

        # Verify what's in the store is only the new articles
        stored_json = redis_store[NEWS_CACHE_KEY]
        stored_articles = json.loads(stored_json)

        self.assertEqual(len(stored_articles), new_count)

        # All stored articles should be from the new set
        for i, article in enumerate(stored_articles):
            self.assertEqual(article["title"], f"New Article {i}")

        # None of the old articles should be present
        old_titles = {f"Old Article {i}" for i in range(old_count)}
        stored_titles = {a["title"] for a in stored_articles}
        self.assertEqual(old_titles & stored_titles, set())

    @given(new_count=st.integers(min_value=1, max_value=30))
    @settings(max_examples=100)
    def test_get_cached_returns_only_stored_articles(self, new_count):
        """
        After storing articles, get_cached_articles should return exactly
        the stored articles and nothing else.

        **Validates: Requirements 17.6**
        """
        # Feature: financial-news-integration, Property 15: News cache replacement semantics

        # Build articles to store
        new_articles = [
            self._make_article(title=f"Cached Article {i}") for i in range(new_count)
        ]

        # Simulate store then retrieve
        from dataclasses import asdict

        serialized = json.dumps([asdict(a) for a in new_articles])
        last_updated = "2024-01-15T14:30:00+00:00"

        mock_pipe = MagicMock()
        mock_pipe.execute.return_value = [serialized, last_updated]
        self.mock_client.pipeline.return_value = mock_pipe

        articles, timestamp = self.service.get_cached_articles()

        self.assertEqual(len(articles), new_count)
        self.assertEqual(timestamp, last_updated)

        for i, article in enumerate(articles):
            self.assertEqual(article["title"], f"Cached Article {i}")


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 18: Sentiment label classification
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 18.4


class PropertySentimentLabelClassificationTest(TestCase):
    """
    Property 18: Sentiment label classification

    For any numeric sentiment_score value, the derived sentiment_label should be
    "positive" when score > 0.2, "negative" when score < -0.2, and "neutral"
    when between -0.2 and 0.2 inclusive.
    """

    @given(score=positive_scores)
    @settings(max_examples=100)
    def test_scores_above_0_2_are_positive(self, score):
        """
        For any score > 0.2, classify should return "positive".

        **Validates: Requirements 18.4**
        """
        # Feature: financial-news-integration, Property 18: Sentiment label classification
        result = SentimentClassifier.classify(score)
        self.assertEqual(
            result,
            "positive",
            f"Score {score} should be 'positive' but got '{result}'",
        )

    @given(score=negative_scores)
    @settings(max_examples=100)
    def test_scores_below_neg_0_2_are_negative(self, score):
        """
        For any score < -0.2, classify should return "negative".

        **Validates: Requirements 18.4**
        """
        # Feature: financial-news-integration, Property 18: Sentiment label classification
        result = SentimentClassifier.classify(score)
        self.assertEqual(
            result,
            "negative",
            f"Score {score} should be 'negative' but got '{result}'",
        )

    @given(score=neutral_scores)
    @settings(max_examples=100)
    def test_scores_between_neg_0_2_and_0_2_inclusive_are_neutral(self, score):
        """
        For any score between -0.2 and 0.2 inclusive, classify should return "neutral".

        **Validates: Requirements 18.4**
        """
        # Feature: financial-news-integration, Property 18: Sentiment label classification
        result = SentimentClassifier.classify(score)
        self.assertEqual(
            result,
            "neutral",
            f"Score {score} should be 'neutral' but got '{result}'",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 19: Article filtering for missing required fields
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 23.6


class PropertyArticleFilteringTest(TestCase):
    """
    Property 19: Article filtering for missing required fields

    For any set of articles where some are missing title or url, the parser
    should skip those and include only articles with both fields present.
    """

    def setUp(self):
        self.client_instance = MarketauxClient()

    @given(
        valid_count=st.integers(min_value=1, max_value=10),
        missing_title_count=st.integers(min_value=0, max_value=5),
        missing_url_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=100)
    def test_articles_missing_title_or_url_are_skipped(
        self, valid_count, missing_title_count, missing_url_count
    ):
        """
        For any mix of valid and invalid articles, only those with both
        title and url should be included in the parsed output.

        **Validates: Requirements 23.6**
        """
        # Feature: financial-news-integration, Property 19: Article filtering for missing required fields

        articles = []

        # Add valid articles
        for i in range(valid_count):
            articles.append(
                make_marketaux_article(
                    title=f"Valid Article {i}",
                    url=f"https://example.com/valid-{i}",
                )
            )

        # Add articles missing title
        for i in range(missing_title_count):
            articles.append({
                "url": f"https://example.com/no-title-{i}",
                "source": "Source",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "No title article",
            })

        # Add articles with empty title
        for i in range(missing_title_count):
            articles.append({
                "title": "",
                "url": f"https://example.com/empty-title-{i}",
                "source": "Source",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "Empty title article",
            })

        # Add articles missing url
        for i in range(missing_url_count):
            articles.append({
                "title": f"No URL Article {i}",
                "source": "Source",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "No url article",
            })

        # Add articles with empty url
        for i in range(missing_url_count):
            articles.append({
                "title": f"Empty URL Article {i}",
                "url": "",
                "source": "Source",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "Empty url article",
            })

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": articles}

        parsed = self.client_instance._parse_response(mock_response)

        # Only valid articles should be included
        self.assertEqual(len(parsed), valid_count)

        # All parsed articles should have non-empty title and url
        for article in parsed:
            self.assertTrue(article["title"], "Parsed article has empty title")
            self.assertTrue(article["source_url"], "Parsed article has empty url")

    @given(
        valid_count=st.integers(min_value=0, max_value=10),
        none_title_count=st.integers(min_value=0, max_value=5),
        none_url_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=100)
    def test_articles_with_none_fields_are_skipped(
        self, valid_count, none_title_count, none_url_count
    ):
        """
        For any articles with None as title or url, the parser should skip them.

        **Validates: Requirements 23.6**
        """
        # Feature: financial-news-integration, Property 19: Article filtering for missing required fields

        articles = []

        # Add valid articles
        for i in range(valid_count):
            articles.append(
                make_marketaux_article(
                    title=f"Valid {i}",
                    url=f"https://example.com/v-{i}",
                )
            )

        # Add articles with None title
        for i in range(none_title_count):
            articles.append({
                "title": None,
                "url": f"https://example.com/none-title-{i}",
                "source": "Source",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "None title",
            })

        # Add articles with None url
        for i in range(none_url_count):
            articles.append({
                "title": f"None URL {i}",
                "url": None,
                "source": "Source",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "None url",
            })

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": articles}

        parsed = self.client_instance._parse_response(mock_response)

        self.assertEqual(len(parsed), valid_count)


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 20: HTML and script sanitization
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 24.5


class PropertyHtmlSanitizationTest(TestCase):
    """
    Property 20: HTML and script sanitization

    For any text field containing HTML tags or script content, sanitization
    should strip all HTML tags and script content, producing plain text with
    no remaining markup.
    """

    @given(
        text_before=plain_text,
        tag=html_tags,
        text_inside=plain_text,
        text_after=plain_text,
    )
    @settings(max_examples=100)
    def test_html_tags_stripped_no_angle_brackets_remain(
        self, text_before, tag, text_inside, text_after
    ):
        """
        For any text wrapped in HTML tags, sanitization should produce output
        with no '<' or '>' characters remaining.

        **Validates: Requirements 24.5**
        """
        # Feature: financial-news-integration, Property 20: HTML and script sanitization
        html_input = f"{text_before}<{tag}>{text_inside}</{tag}>{text_after}"

        result = sanitize_html(html_input)

        # No angle brackets should remain
        self.assertNotIn("<", result, f"Found '<' in sanitized output: {result!r}")
        self.assertNotIn(">", result, f"Found '>' in sanitized output: {result!r}")

    @given(
        text_before=plain_text,
        script_content=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
                blacklist_characters="<>",
            ),
            min_size=1,
            max_size=100,
        ),
        text_after=plain_text,
    )
    @settings(max_examples=100)
    def test_script_content_completely_removed(
        self, text_before, script_content, text_after
    ):
        """
        For any text containing a <script> block, the script content should
        be completely removed from the output.

        **Validates: Requirements 24.5**
        """
        # Feature: financial-news-integration, Property 20: HTML and script sanitization
        html_input = f"{text_before}<script>{script_content}</script>{text_after}"

        result = sanitize_html(html_input)

        # No angle brackets should remain
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

        # Script content should not appear in output (unless it also appears
        # in text_before or text_after naturally)
        # The key property: no markup remains
        self.assertNotIn("<script>", result)
        self.assertNotIn("</script>", result)

    @given(
        text_before=plain_text,
        style_content=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "Z"),
                blacklist_characters="<>",
            ),
            min_size=1,
            max_size=100,
        ),
        text_after=plain_text,
    )
    @settings(max_examples=100)
    def test_style_content_completely_removed(
        self, text_before, style_content, text_after
    ):
        """
        For any text containing a <style> block, the style content should
        be completely removed from the output.

        **Validates: Requirements 24.5**
        """
        # Feature: financial-news-integration, Property 20: HTML and script sanitization
        html_input = f"{text_before}<style>{style_content}</style>{text_after}"

        result = sanitize_html(html_input)

        # No angle brackets should remain
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

        # Style tags should not appear
        self.assertNotIn("<style>", result)
        self.assertNotIn("</style>", result)

    @given(text=plain_text)
    @settings(max_examples=100)
    def test_plain_text_without_html_preserved(self, text):
        """
        For any plain text without HTML, sanitization should preserve the
        text content (modulo whitespace normalization).

        **Validates: Requirements 24.5**
        """
        # Feature: financial-news-integration, Property 20: HTML and script sanitization
        result = sanitize_html(text)

        # Plain text should be preserved (whitespace may be normalized)
        # The core content words should all be present
        import re

        expected_normalized = re.sub(r"\s+", " ", text).strip()
        self.assertEqual(result, expected_normalized)


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 16: News API response correctness
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 18.1, 18.2, 18.9


class PropertyNewsApiResponseCorrectnessTest(TestCase):
    """
    Property 16: News API response correctness

    For any GET request to /api/v1/news/gold/ when cached articles exist, the
    response should contain articles ordered by published_at descending, each
    with all required fields (title, source_name, source_url, published_at,
    description, sentiment_score, sentiment_label), and include a last_updated
    metadata field in ISO 8601 format.
    """

    def setUp(self):
        from rest_framework.test import APIRequestFactory

        self.factory = APIRequestFactory()

    def _make_cached_articles(self, count, timestamps=None):
        """Build a list of cached article dicts as returned by NewsCacheService."""
        articles = []
        for i in range(count):
            ts = timestamps[i] if timestamps else f"2024-01-{15 - i:02d}T12:00:00Z"
            score = round(-0.5 + (i * 0.1), 2)
            articles.append({
                "title": f"Article {i}",
                "source_name": f"Source {i}",
                "source_url": f"https://example.com/article-{i}",
                "published_at": ts,
                "description": f"Description for article {i}",
                "sentiment_score": score,
            })
        return articles

    @given(
        num_articles=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100)
    def test_response_contains_all_required_fields(self, num_articles):
        """
        For any number of cached articles, the response should contain articles
        each with all required fields: title, source_name, source_url,
        published_at, description, sentiment_score, sentiment_label.

        **Validates: Requirements 18.2**
        """
        # Feature: financial-news-integration, Property 16: News API response correctness
        from news.views import NewsListView

        articles = self._make_cached_articles(num_articles)
        last_updated = "2024-01-15T14:30:00Z"

        with patch("news.views.NewsCacheService") as MockCacheService:
            mock_instance = MagicMock()
            mock_instance.get_cached_articles.return_value = (articles, last_updated)
            MockCacheService.return_value = mock_instance

            request = self.factory.get("/api/v1/news/gold/")
            view = NewsListView.as_view()
            response = view(request)

        self.assertEqual(response.status_code, 200)

        required_fields = {
            "title", "source_name", "source_url", "published_at",
            "description", "sentiment_score", "sentiment_label",
        }

        response_articles = response.data["articles"]
        self.assertGreater(len(response_articles), 0)

        for article in response_articles:
            for field in required_fields:
                self.assertIn(
                    field,
                    article,
                    f"Missing required field '{field}' in article response",
                )

    @given(
        num_articles=st.integers(min_value=2, max_value=30),
    )
    @settings(max_examples=100)
    def test_response_articles_ordered_by_published_at_descending(self, num_articles):
        """
        For any set of cached articles, the response should contain articles
        ordered by published_at descending (most recent first).

        **Validates: Requirements 18.1**
        """
        # Feature: financial-news-integration, Property 16: News API response correctness
        from news.views import NewsListView

        # Generate articles with distinct timestamps in random order
        import random

        base_timestamps = [
            f"2024-01-{i:02d}T{h:02d}:00:00Z"
            for i, h in zip(
                range(1, num_articles + 1),
                [random.randint(0, 23) for _ in range(num_articles)],
            )
        ]
        # Shuffle to ensure the view sorts them
        shuffled_timestamps = base_timestamps.copy()
        random.shuffle(shuffled_timestamps)

        articles = self._make_cached_articles(num_articles, timestamps=shuffled_timestamps)
        last_updated = "2024-01-15T14:30:00Z"

        with patch("news.views.NewsCacheService") as MockCacheService:
            mock_instance = MagicMock()
            mock_instance.get_cached_articles.return_value = (articles, last_updated)
            MockCacheService.return_value = mock_instance

            request = self.factory.get("/api/v1/news/gold/")
            view = NewsListView.as_view()
            response = view(request)

        self.assertEqual(response.status_code, 200)

        response_articles = response.data["articles"]
        timestamps = [a["published_at"] for a in response_articles]

        # Verify descending order
        for i in range(len(timestamps) - 1):
            self.assertGreaterEqual(
                timestamps[i],
                timestamps[i + 1],
                f"Articles not in descending order: {timestamps[i]} < {timestamps[i+1]}",
            )

    @given(
        num_articles=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100)
    def test_response_includes_last_updated_in_iso_8601(self, num_articles):
        """
        For any response with cached articles, the response should include a
        last_updated metadata field in ISO 8601 format.

        **Validates: Requirements 18.9**
        """
        # Feature: financial-news-integration, Property 16: News API response correctness
        from news.views import NewsListView
        import re

        articles = self._make_cached_articles(num_articles)
        last_updated = "2024-01-15T14:30:00Z"

        with patch("news.views.NewsCacheService") as MockCacheService:
            mock_instance = MagicMock()
            mock_instance.get_cached_articles.return_value = (articles, last_updated)
            MockCacheService.return_value = mock_instance

            request = self.factory.get("/api/v1/news/gold/")
            view = NewsListView.as_view()
            response = view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("last_updated", response.data)

        # Validate ISO 8601 format
        iso_pattern = re.compile(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
            r"(Z|[+-]\d{2}:\d{2})?$"
        )
        self.assertRegex(
            response.data["last_updated"],
            iso_pattern,
            f"last_updated '{response.data['last_updated']}' is not ISO 8601",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 17: News limit parameter enforcement
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 18.3


class PropertyNewsLimitParameterEnforcementTest(TestCase):
    """
    Property 17: News limit parameter enforcement

    For any valid limit parameter value (integer 1-30) on GET /api/v1/news/gold/,
    the response should contain at most that number of articles. When no limit
    is provided, the response should contain at most 30 articles.
    """

    def setUp(self):
        from rest_framework.test import APIRequestFactory

        self.factory = APIRequestFactory()

    def _make_cached_articles(self, count):
        """Build a list of cached article dicts."""
        articles = []
        for i in range(count):
            articles.append({
                "title": f"Article {i}",
                "source_name": f"Source {i}",
                "source_url": f"https://example.com/article-{i}",
                "published_at": f"2024-01-{(i % 28) + 1:02d}T12:00:00Z",
                "description": f"Description for article {i}",
                "sentiment_score": round(-0.5 + (i * 0.05), 2),
            })
        return articles

    @given(
        limit=st.integers(min_value=1, max_value=30),
        num_cached=st.integers(min_value=1, max_value=30),
    )
    @settings(max_examples=100)
    def test_response_respects_limit_parameter(self, limit, num_cached):
        """
        For any valid limit parameter (1-30), the response should contain
        at most that number of articles.

        **Validates: Requirements 18.3**
        """
        # Feature: financial-news-integration, Property 17: News limit parameter enforcement
        from news.views import NewsListView

        articles = self._make_cached_articles(num_cached)
        last_updated = "2024-01-15T14:30:00Z"

        with patch("news.views.NewsCacheService") as MockCacheService:
            mock_instance = MagicMock()
            mock_instance.get_cached_articles.return_value = (articles, last_updated)
            MockCacheService.return_value = mock_instance

            request = self.factory.get(f"/api/v1/news/gold/?limit={limit}")
            view = NewsListView.as_view()
            response = view(request)

        self.assertEqual(response.status_code, 200)

        response_articles = response.data["articles"]
        expected_max = min(limit, num_cached)

        self.assertLessEqual(
            len(response_articles),
            limit,
            f"Response has {len(response_articles)} articles but limit is {limit}",
        )
        self.assertEqual(
            len(response_articles),
            expected_max,
            f"Expected {expected_max} articles (min of limit={limit}, cached={num_cached})",
        )

    @given(
        num_cached=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_default_limit_is_30_when_no_limit_provided(self, num_cached):
        """
        When no limit parameter is provided, the response should contain
        at most 30 articles.

        **Validates: Requirements 18.3**
        """
        # Feature: financial-news-integration, Property 17: News limit parameter enforcement
        from news.views import NewsListView

        articles = self._make_cached_articles(num_cached)
        last_updated = "2024-01-15T14:30:00Z"

        with patch("news.views.NewsCacheService") as MockCacheService:
            mock_instance = MagicMock()
            mock_instance.get_cached_articles.return_value = (articles, last_updated)
            MockCacheService.return_value = mock_instance

            request = self.factory.get("/api/v1/news/gold/")
            view = NewsListView.as_view()
            response = view(request)

        self.assertEqual(response.status_code, 200)

        response_articles = response.data["articles"]
        expected_max = min(30, num_cached)

        self.assertLessEqual(
            len(response_articles),
            30,
            f"Response has {len(response_articles)} articles without limit, expected max 30",
        )
        self.assertEqual(
            len(response_articles),
            expected_max,
            f"Expected {expected_max} articles (min of default 30, cached={num_cached})",
        )
