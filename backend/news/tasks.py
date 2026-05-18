"""
Celery tasks for scheduled news fetching.

The fetch_news task orchestrates the news pipeline:
1. Fetch articles from Marketaux API
2. Sanitize text fields (strip HTML/scripts)
3. Classify sentiment from numeric scores
4. Store processed articles in Redis cache

This task operates independently from the data ingestion and ML pipelines.
"""

import logging
from datetime import datetime, timezone

import redis
from celery import shared_task

from news.schemas import NewsArticle
from news.services import (
    MarketauxClient,
    NewsCacheService,
    SentimentClassifier,
    sanitize_html,
)

logger = logging.getLogger(__name__)


@shared_task(name="news.tasks.fetch_news")
def fetch_news() -> None:
    """Fetch gold-related news articles, process, and cache them.

    Orchestration steps:
    1. Call MarketauxClient.fetch_articles() to retrieve raw articles
    2. Sanitize text fields (title, description, source_name)
    3. Classify sentiment from numeric score
    4. Store processed NewsArticle objects via NewsCacheService

    Error handling:
    - Empty response: retain previous cache, log warning
    - Fetch failure (all retries exhausted internally by client): retain previous cache, log error
    - Redis unreachable on store: log error, discard fetched articles
    """
    client = MarketauxClient()

    # Fetch articles from Marketaux API
    # MarketauxClient handles its own retries internally
    raw_articles = client.fetch_articles()

    # Handle empty response — retain previous cache
    if not raw_articles:
        logger.warning(
            "fetch_news: empty response from Marketaux API at %s. "
            "Retaining previous cache.",
            datetime.now(timezone.utc).isoformat(),
        )
        return

    # Process articles: sanitize fields and classify sentiment
    processed_articles: list[NewsArticle] = []
    for raw in raw_articles:
        title = sanitize_html(raw.get("title", ""))
        source_name = sanitize_html(raw.get("source_name", ""))
        source_url = raw.get("source_url", "")
        published_at = raw.get("published_at", "")
        description = sanitize_html(raw.get("description", ""))
        sentiment_score = float(raw.get("sentiment_score", 0.0))
        sentiment_label = SentimentClassifier.classify(sentiment_score)

        article = NewsArticle(
            title=title,
            source_name=source_name,
            source_url=source_url,
            published_at=published_at,
            description=description,
            sentiment_score=sentiment_score,
            sentiment_label=sentiment_label,
        )
        processed_articles.append(article)

    # Store in Redis cache
    cache_service = NewsCacheService()
    try:
        cache_service.store_articles(processed_articles)
    except redis.RedisError as exc:
        logger.error(
            "fetch_news: Redis unreachable when storing articles at %s. "
            "Error: %s. Discarding fetched articles.",
            datetime.now(timezone.utc).isoformat(),
            exc,
        )
        return

    # Success — log timestamp and article count
    logger.info(
        "fetch_news: successfully fetched and cached %d articles at %s.",
        len(processed_articles),
        datetime.now(timezone.utc).isoformat(),
    )
