"""Views for the prices app."""

import hashlib
import json
import logging
from datetime import date, timedelta

import redis
from django.conf import settings
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from prices.models import GoldPrice
from prices.serializers import GoldPriceSerializer

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 minutes in seconds
MAX_RECORDS = 1095


def _get_redis_client():
    """Get a Redis client, returning None if unavailable."""
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except (redis.ConnectionError, redis.RedisError) as exc:
        logger.error("Redis unavailable, bypassing cache: %s", exc)
        return None


def _build_cache_key(request_path: str) -> str:
    """Build a cache key from the full request path including query params."""
    query_hash = hashlib.md5(request_path.encode()).hexdigest()
    return f"cache:historical:{query_hash}"


def _parse_date(value: str) -> date | None:
    """Parse a YYYY-MM-DD date string, returning None if invalid."""
    try:
        parts = value.split("-")
        if len(parts) != 3:
            return None
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        return date(year, month, day)
    except (ValueError, TypeError):
        return None


class HistoricalPriceView(APIView):
    """
    GET /api/v1/prices/historical

    Returns historical gold price records within a date range.
    Supports start_date and end_date query params (ISO 8601 YYYY-MM-DD).
    Defaults to last 365 days if not specified.
    """

    def get(self, request: Request) -> Response:
        # Parse and validate date parameters
        today = date.today()
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")

        if start_date_str:
            start_date = _parse_date(start_date_str)
            if start_date is None:
                return Response(
                    {
                        "error": "Invalid start_date format. Expected YYYY-MM-DD.",
                        "parameter": "start_date",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            start_date = today - timedelta(days=365)

        if end_date_str:
            end_date = _parse_date(end_date_str)
            if end_date is None:
                return Response(
                    {
                        "error": "Invalid end_date format. Expected YYYY-MM-DD.",
                        "parameter": "end_date",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            end_date = today

        # Validate start_date <= end_date
        if start_date > end_date:
            return Response(
                {
                    "error": "start_date must not be after end_date.",
                    "parameter": "start_date",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Try cache first
        full_path = request.get_full_path()
        cache_key = _build_cache_key(full_path)
        redis_client = _get_redis_client()

        if redis_client:
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    return Response(json.loads(cached), status=status.HTTP_200_OK)
            except (redis.RedisError, json.JSONDecodeError) as exc:
                logger.warning("Cache read failed: %s", exc)

        # Query database
        queryset = GoldPrice.objects.filter(
            date__gte=start_date, date__lte=end_date
        ).order_by("date")[:MAX_RECORDS]

        serializer = GoldPriceSerializer(queryset, many=True)
        data = serializer.data

        # Store in cache
        if redis_client:
            try:
                redis_client.setex(cache_key, CACHE_TTL, json.dumps(data))
            except redis.RedisError as exc:
                logger.warning("Cache write failed: %s", exc)

        return Response(data, status=status.HTTP_200_OK)
