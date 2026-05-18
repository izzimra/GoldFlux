"""
News services: Marketaux API client, Redis cache helpers, and utilities.
"""

import json
import logging
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import StringIO
from typing import Optional

import redis
import requests
from django.conf import settings

from news.schemas import NewsArticle

logger = logging.getLogger(__name__)

# Cache configuration
NEWS_CACHE_KEY = "news:gold:articles"
NEWS_LAST_UPDATED_KEY = "news:gold:last_updated"
NEWS_CACHE_TTL = 18000  # 5 hours in seconds


class NewsCacheService:
    """Manages news article caching in Redis."""

    def __init__(self):
        redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        self._redis_client = redis.Redis.from_url(
            redis_url, decode_responses=True, socket_timeout=2
        )

    def store_articles(self, articles: list[NewsArticle]) -> None:
        """
        Replaces cached articles with new set, TTL = 5 hours.

        Serializes articles to JSON, stores in Redis with key 'news:gold:articles'
        and TTL of 5 hours. Also stores 'news:gold:last_updated' timestamp.
        Replaces previous cached set entirely (not append).
        """
        serialized = json.dumps([asdict(article) for article in articles])
        last_updated = datetime.now(timezone.utc).isoformat()

        pipe = self._redis_client.pipeline()
        pipe.set(NEWS_CACHE_KEY, serialized, ex=NEWS_CACHE_TTL)
        pipe.set(NEWS_LAST_UPDATED_KEY, last_updated, ex=NEWS_CACHE_TTL)
        pipe.execute()

        logger.info(
            "Stored %d articles in cache, last_updated=%s",
            len(articles),
            last_updated,
        )

    def get_cached_articles(self) -> tuple[list[dict], str | None]:
        """
        Returns (articles, last_updated_iso) or ([], None) if cache is empty.

        Retrieves articles from Redis, deserializes from JSON, and returns
        as a tuple of (list of article dicts, last_updated ISO timestamp).
        """
        pipe = self._redis_client.pipeline()
        pipe.get(NEWS_CACHE_KEY)
        pipe.get(NEWS_LAST_UPDATED_KEY)
        results = pipe.execute()

        raw_articles = results[0]
        last_updated = results[1]

        if raw_articles is None:
            return [], None

        try:
            articles = json.loads(raw_articles)
        except (json.JSONDecodeError, TypeError):
            logger.error("Failed to deserialize cached articles")
            return [], None

        return articles, last_updated


class MarketauxClient:
    """HTTP client for Marketaux API with retry and error handling.

    Reads configuration from environment variables:
    - NEWS_API_BASE_URL: API base URL (default: https://api.marketaux.com)
    - NEWS_API_KEY: API authentication token (required)
    - NEWS_API_KEYWORDS: Comma-separated search terms (default: gold,XAU,commodities)
    """

    DEFAULT_BASE_URL = "https://api.marketaux.com"
    DEFAULT_KEYWORDS = "gold,XAU,commodities"
    MAX_RETRIES = 3
    BACKOFF_BASE = 5  # seconds

    def __init__(self) -> None:
        self.base_url = os.environ.get("NEWS_API_BASE_URL", self.DEFAULT_BASE_URL).rstrip("/")
        self.api_key = os.environ.get("NEWS_API_KEY", "")
        self.keywords = os.environ.get("NEWS_API_KEYWORDS", self.DEFAULT_KEYWORDS)

    def is_configured(self) -> bool:
        """Check if the API key is configured. Logs error if missing."""
        if not self.api_key:
            logger.error(
                "NEWS_API_KEY environment variable is not set or empty. "
                "News fetching will not be scheduled."
            )
            return False
        return True

    def fetch_articles(self) -> list[dict]:
        """Fetch articles from Marketaux API with exponential backoff retry.

        Returns a list of parsed article dicts ready for NewsArticle construction.
        Retries up to 3 times with exponential backoff (5s base) on failure.
        """
        # Re-read keywords each call to support runtime updates without restart
        self.keywords = os.environ.get("NEWS_API_KEYWORDS", self.DEFAULT_KEYWORDS)

        url = f"{self.base_url}/v1/news/all"
        params = {
            "api_token": self.api_key,
            "search": self.keywords,
            "limit": 30,
        }

        last_exception: Optional[Exception] = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                return self._parse_response(response)
            except requests.exceptions.HTTPError as exc:
                last_exception = exc
                logger.warning(
                    "Marketaux API HTTP error (attempt %d/%d): %s",
                    attempt,
                    self.MAX_RETRIES,
                    exc,
                )
            except requests.exceptions.RequestException as exc:
                last_exception = exc
                logger.warning(
                    "Marketaux API request error (attempt %d/%d): %s",
                    attempt,
                    self.MAX_RETRIES,
                    exc,
                )

            if attempt < self.MAX_RETRIES:
                backoff = self.BACKOFF_BASE * (2 ** (attempt - 1))
                time.sleep(backoff)

        # All retries exhausted
        logger.error(
            "Marketaux API: all %d retry attempts failed. Last error: %s",
            self.MAX_RETRIES,
            last_exception,
        )
        return []

    def _parse_response(self, response: requests.Response) -> list[dict]:
        """Parse Marketaux API JSON response and extract article data.

        Handles malformed JSON by logging the first 500 chars of the response.
        Skips articles missing required fields (title or url).
        """
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError):
            raw_text = response.text[:500]
            logger.error(
                "Marketaux API returned malformed JSON. First 500 chars: %s",
                raw_text,
            )
            return []

        articles_data = data.get("data", [])
        if not isinstance(articles_data, list):
            logger.error("Marketaux API 'data' field is not a list.")
            return []

        parsed_articles: list[dict] = []

        for article in articles_data:
            if not isinstance(article, dict):
                continue

            title = article.get("title")
            url = article.get("url")

            # Skip articles missing required fields
            if not title:
                logger.warning(
                    "Skipping article missing required field 'title': %s",
                    article.get("url", "unknown"),
                )
                continue
            if not url:
                logger.warning(
                    "Skipping article missing required field 'url': %s",
                    article.get("title", "unknown"),
                )
                continue

            # Extract sentiment score from entities
            sentiment_score = self._extract_sentiment_score(article)

            # Extract description, truncate to 300 chars
            description = article.get("description", "") or ""
            description = description[:300]

            parsed_articles.append(
                {
                    "title": title,
                    "source_name": article.get("source", "") or "",
                    "source_url": url,
                    "published_at": article.get("published_at", "") or "",
                    "description": description,
                    "sentiment_score": sentiment_score,
                }
            )

        return parsed_articles

    @staticmethod
    def _extract_sentiment_score(article: dict) -> float:
        """Extract sentiment score from article entities.

        Returns 0.0 if entities array is empty or score is missing.
        """
        entities = article.get("entities", [])
        if not entities or not isinstance(entities, list):
            return 0.0

        # Look for sentiment_score in entities
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            score = entity.get("sentiment_score")
            if score is not None:
                try:
                    return float(score)
                except (TypeError, ValueError):
                    continue

        return 0.0


class SentimentClassifier:
    """Derives sentiment labels from numeric scores."""

    @staticmethod
    def classify(score: float) -> str:
        """Returns 'positive', 'neutral', or 'negative'.

        Classification thresholds:
        - score > 0.2  → "positive"
        - score < -0.2 → "negative"
        - otherwise    → "neutral"
        """
        if score > 0.2:
            return "positive"
        elif score < -0.2:
            return "negative"
        return "neutral"


class _HTMLTextExtractor(HTMLParser):
    """HTML parser that extracts plain text, skipping script/style content."""

    def __init__(self):
        super().__init__()
        self._result = StringIO()
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style"):
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._result.write(data)

    def get_text(self) -> str:
        return self._result.getvalue()


def sanitize_html(text: str) -> str:
    """Strip all HTML tags and script/style content from text, producing plain text.

    Handles:
    - Removing all HTML tags (e.g., <p>, <div>, <a>, etc.)
    - Removing <script> and <style> tags along with their content
    - Producing clean plain text output with no remaining markup

    Args:
        text: Input string potentially containing HTML markup.

    Returns:
        Plain text with all HTML tags and script content removed.
    """
    if not text:
        return text

    # Remove <script>...</script> and <style>...</style> blocks entirely
    # (including content) using regex for robustness against malformed HTML
    cleaned = re.sub(
        r"<script[\s>].*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE
    )
    cleaned = re.sub(
        r"<style[\s>].*?</style>", "", cleaned, flags=re.DOTALL | re.IGNORECASE
    )

    # Use the HTML parser to strip remaining tags and extract text
    extractor = _HTMLTextExtractor()
    extractor.feed(cleaned)
    result = extractor.get_text()

    # Collapse multiple whitespace into single spaces and strip
    result = re.sub(r"\s+", " ", result).strip()

    return result
