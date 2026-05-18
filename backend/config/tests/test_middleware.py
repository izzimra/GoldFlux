"""
Unit tests for RateLimitMiddleware.
"""

from unittest.mock import MagicMock, patch

from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, TestCase, override_settings

from config.middleware import RateLimitMiddleware


class RateLimitMiddlewareTest(TestCase):
    """Tests for the RateLimitMiddleware class."""

    def setUp(self):
        self.factory = RequestFactory()
        self.get_response = MagicMock(return_value=HttpResponse("OK"))
        self.middleware = RateLimitMiddleware(self.get_response)

    @patch("config.middleware.redis.Redis.from_url")
    def test_allows_requests_under_limit(self, mock_redis_from_url):
        """Requests under the rate limit should pass through."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 1
        mock_redis_from_url.return_value = mock_client

        # Reset the cached client
        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.get_response.assert_called_once_with(request)

    @patch("config.middleware.redis.Redis.from_url")
    def test_blocks_requests_over_limit(self, mock_redis_from_url):
        """Requests exceeding 100 in a window should get HTTP 429."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 101
        mock_redis_from_url.return_value = mock_client

        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        response = self.middleware(request)

        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
        self.assertIn("Rate limit exceeded", response.content.decode())

    @patch("config.middleware.redis.Redis.from_url")
    def test_retry_after_header_is_positive_integer(self, mock_redis_from_url):
        """Retry-After header should be a positive integer string."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 101
        mock_redis_from_url.return_value = mock_client

        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/news/gold/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        response = self.middleware(request)

        retry_after = int(response["Retry-After"])
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, 60)

    @patch("config.middleware.redis.Redis.from_url")
    def test_sets_ttl_on_first_request(self, mock_redis_from_url):
        """TTL should be set on the Redis key for the first request in a window."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 1
        mock_redis_from_url.return_value = mock_client

        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        self.middleware(request)

        mock_client.expire.assert_called_once()
        args = mock_client.expire.call_args[0]
        self.assertEqual(args[1], 60)

    @patch("config.middleware.redis.Redis.from_url")
    def test_does_not_set_ttl_on_subsequent_requests(self, mock_redis_from_url):
        """TTL should not be reset on subsequent requests in the same window."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 50
        mock_redis_from_url.return_value = mock_client

        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        self.middleware(request)

        mock_client.expire.assert_not_called()

    @patch("config.middleware.redis.Redis.from_url")
    def test_bypasses_rate_limit_when_redis_unavailable(self, mock_redis_from_url):
        """If Redis is unreachable, requests should pass through."""
        import redis as redis_lib

        mock_client = MagicMock()
        mock_client.incr.side_effect = redis_lib.ConnectionError("Connection refused")
        mock_redis_from_url.return_value = mock_client

        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.get_response.assert_called_once_with(request)

    def test_extracts_ip_from_x_forwarded_for(self):
        """Should use the first IP from X-Forwarded-For header."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 1
        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.50, 70.41.3.18"
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        self.middleware(request)

        # Verify the key uses the forwarded IP
        call_args = mock_client.incr.call_args[0][0]
        self.assertIn("203.0.113.50", call_args)
        self.assertNotIn("127.0.0.1", call_args)

    def test_extracts_ip_from_remote_addr(self):
        """Should fall back to REMOTE_ADDR when X-Forwarded-For is absent."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 1
        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "10.0.0.5"

        self.middleware(request)

        call_args = mock_client.incr.call_args[0][0]
        self.assertIn("10.0.0.5", call_args)

    @patch("config.middleware.redis.Redis.from_url")
    def test_allows_exactly_100_requests(self, mock_redis_from_url):
        """The 100th request should still be allowed."""
        mock_client = MagicMock()
        mock_client.incr.return_value = 100
        mock_redis_from_url.return_value = mock_client

        self.middleware._redis_client = mock_client

        request = self.factory.get("/api/v1/prices/historical")
        request.META["REMOTE_ADDR"] = "192.168.1.1"

        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
        self.get_response.assert_called_once_with(request)
