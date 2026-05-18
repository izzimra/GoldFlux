"""Views for the news app."""

import logging

import redis
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from news.services import NewsCacheService, SentimentClassifier

logger = logging.getLogger(__name__)


class NewsListView(APIView):
    """
    GET /api/v1/news/gold/

    Returns cached gold-related news articles as a flattened JSON array.
    Serves directly from Redis cache (cache-first, no external API call).
    Supports optional `limit` query parameter (integer 1-30, default 30).
    """

    def get(self, request: Request) -> Response:
        # Validate limit parameter
        limit_param = request.query_params.get("limit")
        if limit_param is not None:
            try:
                limit = int(limit_param)
            except (ValueError, TypeError):
                return Response(
                    {
                        "error": "Invalid limit parameter. Must be an integer between 1 and 30.",
                        "parameter": "limit",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if limit < 1 or limit > 30:
                return Response(
                    {
                        "error": "Invalid limit parameter. Must be an integer between 1 and 30.",
                        "parameter": "limit",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            limit = 30

        # Fetch from cache
        try:
            cache_service = NewsCacheService()
            articles, last_updated = cache_service.get_cached_articles()
        except redis.RedisError as exc:
            logger.error("Redis unreachable when serving news: %s", exc)
            return Response(
                {
                    "last_updated": None,
                    "articles": [],
                    "message": "news is temporarily unavailable",
                },
                status=status.HTTP_200_OK,
            )

        # Handle empty/expired cache
        if not articles:
            return Response(
                {
                    "last_updated": last_updated,
                    "articles": [],
                    "message": "news data is being fetched",
                },
                status=status.HTTP_200_OK,
            )

        # Enrich articles with sentiment_label and sort by published_at descending
        for article in articles:
            score = article.get("sentiment_score", 0.0)
            article["sentiment_label"] = SentimentClassifier.classify(score)

        # Sort by published_at descending (most recent first)
        articles.sort(key=lambda a: a.get("published_at", ""), reverse=True)

        # Apply limit
        articles = articles[:limit]

        return Response(
            {
                "last_updated": last_updated,
                "articles": articles,
            },
            status=status.HTTP_200_OK,
        )
