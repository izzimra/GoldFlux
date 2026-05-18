"""Views for the predictions app."""

import hashlib
import json
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from predictions.models import ModelMetadata, Prediction
from predictions.serializers import ModelMetadataSerializer, PredictionSerializer

logger = logging.getLogger(__name__)

# Cache TTL for predictions: 60 minutes
PREDICTIONS_CACHE_TTL = 3600


def _get_redis_client():
    """Get a Redis client, returning None if unavailable."""
    try:
        import redis

        client = redis.Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, decode_responses=True
        )
        client.ping()
        return client
    except Exception:
        logger.error("Redis unavailable, bypassing cache")
        return None


def _build_cache_key(request: Request) -> str:
    """Build a cache key from the request path and query parameters."""
    query_string = request.META.get("QUERY_STRING", "")
    raw_key = f"{request.path}?{query_string}"
    query_hash = hashlib.md5(raw_key.encode()).hexdigest()
    return f"cache:predictions:{query_hash}"


class PredictionListView(APIView):
    """
    GET /api/v1/prices/predictions

    Returns a JSON array of Prediction records ordered by predicted_date ascending.
    Implements Redis caching with 60-minute TTL.
    Ignores unrecognized query parameters.
    Returns empty array with message if no predictions exist.
    """

    def get(self, request: Request) -> Response:
        # Try to serve from cache
        redis_client = _get_redis_client()
        if redis_client:
            cache_key = _build_cache_key(request)
            try:
                cached = redis_client.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    return Response(data)
            except Exception:
                logger.error("Error reading from Redis cache, serving from DB")

        # Query database
        predictions = Prediction.objects.all().order_by("predicted_date")

        if not predictions.exists():
            response_data = {"data": [], "message": "Predictions are pending"}
        else:
            serializer = PredictionSerializer(predictions, many=True)
            response_data = serializer.data

        # Store in cache
        if redis_client:
            try:
                cache_key = _build_cache_key(request)
                renderer = JSONRenderer()
                json_data = renderer.render(response_data).decode("utf-8")
                redis_client.setex(cache_key, PREDICTIONS_CACHE_TTL, json_data)
            except Exception:
                logger.error("Error writing to Redis cache")

        return Response(response_data)


class ModelMetadataView(APIView):
    """GET /api/v1/model/metadata

    Returns the latest model metadata (by training_date).
    Returns 404 if no model has been trained.
    """

    def get(self, request: Request) -> Response:
        metadata = ModelMetadata.objects.order_by("-training_date").first()
        if metadata is None:
            return Response(
                {"error": "No trained model is available"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = ModelMetadataSerializer(metadata)
        return Response(serializer.data, status=status.HTTP_200_OK)
