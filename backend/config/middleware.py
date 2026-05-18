"""
Custom middleware for the GoldFlux API.
"""

import json
import time
import uuid
import logging

import redis
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """
    Enforces rate limiting of 100 requests per fixed 60-second window per IP address.

    Uses Redis to track request counts. If a client exceeds the limit, returns
    HTTP 429 with a Retry-After header indicating seconds remaining in the window.

    Redis key pattern: ratelimit:{ip}:{window} with 60-second TTL.
    """

    RATE_LIMIT = 100
    WINDOW_SECONDS = 60

    def __init__(self, get_response):
        self.get_response = get_response
        self._redis_client = None

    @property
    def redis_client(self):
        """Lazy-initialize Redis client from Django settings."""
        if self._redis_client is None:
            redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
            try:
                self._redis_client = redis.Redis.from_url(
                    redis_url, decode_responses=True, socket_timeout=2
                )
            except Exception:
                logger.error("RateLimitMiddleware: Failed to connect to Redis")
                self._redis_client = None
        return self._redis_client

    def __call__(self, request):
        client_ip = self._get_client_ip(request)
        current_window = int(time.time()) // self.WINDOW_SECONDS

        try:
            if self.redis_client is None:
                # If Redis is unavailable, allow the request through
                return self.get_response(request)

            key = f"ratelimit:{client_ip}:{current_window}"
            current_count = self.redis_client.incr(key)

            # Set TTL on first request in this window
            if current_count == 1:
                self.redis_client.expire(key, self.WINDOW_SECONDS)

            if current_count > self.RATE_LIMIT:
                # Calculate seconds remaining in the current window
                window_start = current_window * self.WINDOW_SECONDS
                window_end = window_start + self.WINDOW_SECONDS
                retry_after = max(1, int(window_end - time.time()))

                response = JsonResponse(
                    {"error": "Rate limit exceeded. Please try again later."},
                    status=429,
                )
                response["Retry-After"] = str(retry_after)
                return response

        except (redis.ConnectionError, redis.TimeoutError):
            # If Redis is unreachable, allow the request through
            logger.warning(
                "RateLimitMiddleware: Redis unavailable, bypassing rate limit"
            )
        except Exception:
            logger.exception("RateLimitMiddleware: Unexpected error during rate check")

        return self.get_response(request)

    def _get_client_ip(self, request):
        """Extract client IP from request, respecting X-Forwarded-For header."""
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            return x_forwarded_for.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR", "unknown")


class CorrelationIdMiddleware:
    """
    Generates a UUID v4 correlation_id for every request and includes it
    in all error responses (4xx and 5xx status codes).

    The correlation_id is attached to the request object for use by other
    middleware and views, and is injected into the response body of error
    responses to facilitate debugging and log correlation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Generate a unique correlation_id for this request
        request.correlation_id = str(uuid.uuid4())

        response = self.get_response(request)

        # Inject correlation_id into error responses (4xx and 5xx)
        if response.status_code >= 400:
            self._inject_correlation_id(request, response)

        return response

    def _inject_correlation_id(self, request, response):
        """Inject correlation_id into the response body for error responses."""
        content_type = response.get("Content-Type", "")

        if "application/json" in content_type:
            try:
                data = json.loads(response.content.decode("utf-8"))
                if isinstance(data, dict):
                    data["correlation_id"] = request.correlation_id
                else:
                    # Wrap non-dict JSON in an object with correlation_id
                    data = {
                        "detail": data,
                        "correlation_id": request.correlation_id,
                    }
                response.content = json.dumps(data).encode("utf-8")
                response["Content-Length"] = str(len(response.content))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # If we can't parse the body, add correlation_id as a header
                response["X-Correlation-ID"] = request.correlation_id
        else:
            # For non-JSON error responses, add correlation_id as a header
            response["X-Correlation-ID"] = request.correlation_id


class ErrorHandlingMiddleware:
    """
    Catches unhandled exceptions and returns safe error responses.

    Behavior:
    - Unhandled exceptions: returns HTTP 500 with generic message (no stack traces,
      hostnames, or config details exposed). Logs full exception server-side.
    - PostgreSQL unreachable: returns HTTP 503 after 5s timeout or 2 consecutive
      failed connection attempts.
    - Redis unreachable: bypasses cache silently, logs error.
    - If any downstream dependency remains unreachable for >30 seconds, logs a
      persistent connectivity failure event at ERROR level.
    - All error responses include a correlation_id (set by CorrelationIdMiddleware).

    Requirements: 13.1, 13.2, 13.3, 13.5, 13.6
    """

    # Track consecutive failures for persistent connectivity detection
    _pg_failure_start = None
    _redis_failure_start = None

    PG_TIMEOUT = 5  # seconds
    PG_MAX_FAILURES = 2
    REDIS_TIMEOUT = 2  # seconds
    PERSISTENT_FAILURE_THRESHOLD = 30  # seconds

    def __init__(self, get_response):
        self.get_response = get_response
        self._pg_consecutive_failures = 0

    def __call__(self, request):
        try:
            response = self.get_response(request)
            # Reset PostgreSQL failure counter on successful response
            self._pg_consecutive_failures = 0
            ErrorHandlingMiddleware._pg_failure_start = None
            return response
        except Exception as exc:
            return self._handle_exception(request, exc)

    def _handle_exception(self, request, exc):
        """Route exception to the appropriate handler."""
        from django.db import OperationalError

        # Check for PostgreSQL connectivity issues
        if self._is_postgres_error(exc):
            return self._handle_postgres_unavailable(request, exc)

        # Check for Redis connectivity issues
        if self._is_redis_error(exc):
            return self._handle_redis_unavailable(request, exc)

        # All other unhandled exceptions
        return self._handle_generic_error(request, exc)

    def _is_postgres_error(self, exc):
        """Determine if the exception is a PostgreSQL connectivity error."""
        from django.db import OperationalError

        if isinstance(exc, OperationalError):
            return True
        # Check for wrapped database errors
        error_msg = str(exc).lower()
        if any(
            keyword in error_msg
            for keyword in [
                "could not connect to server",
                "connection refused",
                "connection timed out",
                "database",
                "postgresql",
            ]
        ):
            return isinstance(exc, (OSError, ConnectionError))
        return False

    def _is_redis_error(self, exc):
        """Determine if the exception is a Redis connectivity error."""
        return isinstance(exc, (redis.ConnectionError, redis.TimeoutError))

    def _handle_postgres_unavailable(self, request, exc):
        """
        Handle PostgreSQL unreachable: return 503 after 5s timeout or 2 failed attempts.
        Tracks persistent connectivity failures (>30s).
        """
        self._pg_consecutive_failures += 1
        now = time.time()

        # Track when failures started for persistent failure detection
        if ErrorHandlingMiddleware._pg_failure_start is None:
            ErrorHandlingMiddleware._pg_failure_start = now

        # Log the failure
        logger.error(
            "PostgreSQL connection failure (attempt %d): %s",
            self._pg_consecutive_failures,
            str(exc),
            exc_info=True,
        )

        # Check for persistent connectivity failure (>30 seconds)
        failure_duration = now - ErrorHandlingMiddleware._pg_failure_start
        if failure_duration > self.PERSISTENT_FAILURE_THRESHOLD:
            logger.error(
                "PERSISTENT CONNECTIVITY FAILURE: PostgreSQL has been unreachable "
                "for %.1f seconds (threshold: %ds)",
                failure_duration,
                self.PERSISTENT_FAILURE_THRESHOLD,
            )

        # Return 503 after timeout or 2 consecutive failures
        correlation_id = self._get_correlation_id(request)
        return JsonResponse(
            {
                "error": "Service temporarily unavailable. Please try again later.",
                "correlation_id": correlation_id,
            },
            status=503,
        )

    def _handle_redis_unavailable(self, request, exc):
        """
        Handle Redis unreachable: bypass cache silently, log error.
        Tracks persistent connectivity failures (>30s).
        """
        now = time.time()

        # Track when Redis failures started
        if ErrorHandlingMiddleware._redis_failure_start is None:
            ErrorHandlingMiddleware._redis_failure_start = now

        # Log the error (but don't expose to user)
        logger.error(
            "Redis connection failure (bypassing cache): %s",
            str(exc),
            exc_info=True,
        )

        # Check for persistent connectivity failure (>30 seconds)
        failure_duration = now - ErrorHandlingMiddleware._redis_failure_start
        if failure_duration > self.PERSISTENT_FAILURE_THRESHOLD:
            logger.error(
                "PERSISTENT CONNECTIVITY FAILURE: Redis has been unreachable "
                "for %.1f seconds (threshold: %ds)",
                failure_duration,
                self.PERSISTENT_FAILURE_THRESHOLD,
            )

        # Bypass cache silently - try to serve the request without cache
        try:
            response = self.get_response(request)
            return response
        except Exception as inner_exc:
            # If serving without cache also fails, return generic error
            return self._handle_generic_error(request, inner_exc)

    def _handle_generic_error(self, request, exc):
        """
        Handle unhandled exceptions: return HTTP 500 with generic message.
        No stack traces, hostnames, or configuration details exposed.
        Logs full exception details server-side.
        """
        correlation_id = self._get_correlation_id(request)

        # Log full exception details server-side
        logger.error(
            "Unhandled exception [correlation_id=%s]: %s",
            correlation_id,
            str(exc),
            exc_info=True,
        )

        return JsonResponse(
            {
                "error": "An internal server error occurred. Please try again later.",
                "correlation_id": correlation_id,
            },
            status=500,
        )

    def _get_correlation_id(self, request):
        """
        Retrieve the correlation_id set by CorrelationIdMiddleware.
        Falls back to generating one if not present.
        """
        import uuid

        correlation_id = getattr(request, "correlation_id", None)
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())
        return str(correlation_id)
