"""
Property-based tests for middleware layer.

Uses Hypothesis to validate universal properties of the rate limiting,
security headers, and error handling middleware.
"""

import json
import re
import uuid
from unittest.mock import MagicMock, patch

from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, override_settings
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from config.middleware import (
    CorrelationIdMiddleware,
    ErrorHandlingMiddleware,
    RateLimitMiddleware,
)


# ──────────────────────────────────────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────────────────────────────────────

# Valid IPv4 addresses
ipv4_strategy = st.tuples(
    st.integers(min_value=1, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=1, max_value=255),
).map(lambda t: f"{t[0]}.{t[1]}.{t[2]}.{t[3]}")

# API endpoint paths
api_paths = st.sampled_from([
    "/api/v1/prices/historical",
    "/api/v1/prices/predictions",
    "/api/v1/model/metadata",
    "/api/v1/news/gold/",
])

# Request counts that exceed the rate limit
over_limit_counts = st.integers(min_value=101, max_value=500)

# Request counts within the rate limit
under_limit_counts = st.integers(min_value=1, max_value=100)

# HTTP error status codes (4xx and 5xx)
error_status_codes = st.one_of(
    st.integers(min_value=400, max_value=499),
    st.integers(min_value=500, max_value=599),
)

# Strings that might appear in unsafe error responses
unsafe_content_fragments = st.sampled_from([
    "Traceback (most recent call last):",
    "File \"/usr/local/lib/python3.11/",
    "django.db.utils.OperationalError",
    "psycopg2.OperationalError",
    "DATABASES = {",
    "SECRET_KEY =",
    "redis://internal-host:6379",
    "postgresql://admin:password@db-host:5432",
    "192.168.1.100",
    "ip-10-0-1-42.ec2.internal",
])

# HTTP methods
http_methods = st.sampled_from(["get", "post", "put", "patch", "delete"])


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 11: Rate limiting enforcement
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 12.1, 12.2, 24.1, 24.2


class PropertyRateLimitingEnforcementTest(TestCase):
    """
    Property 11: Rate limiting enforcement

    For any IP address making more than 100 requests within a 60-second window
    to any API endpoint, all requests beyond the 100th should receive HTTP 429
    with a Retry-After header indicating seconds remaining in the window.
    """

    def setUp(self):
        self.factory = RequestFactory()
        self.get_response = MagicMock(return_value=HttpResponse("OK", status=200))

    @given(
        ip=ipv4_strategy,
        path=api_paths,
        request_count=over_limit_counts,
    )
    @settings(max_examples=100)
    def test_requests_over_limit_receive_429(self, ip, path, request_count):
        """
        For any IP exceeding 100 requests in a window, subsequent requests
        should receive HTTP 429 with a valid Retry-After header.

        **Validates: Requirements 12.1, 12.2, 24.1, 24.2**
        """
        # Feature: financial-news-integration, Property 11: Rate limiting enforcement
        middleware = RateLimitMiddleware(self.get_response)

        mock_client = MagicMock()
        mock_client.incr.return_value = request_count
        middleware._redis_client = mock_client

        request = self.factory.get(path)
        request.META["REMOTE_ADDR"] = ip

        response = middleware(request)

        # All requests beyond the 100th should get 429
        self.assertEqual(response.status_code, 429)

        # Must include Retry-After header
        self.assertIn("Retry-After", response)

        # Retry-After must be a positive integer <= 60 (window size)
        retry_after = int(response["Retry-After"])
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 60)

    @given(
        ip=ipv4_strategy,
        path=api_paths,
        request_count=under_limit_counts,
    )
    @settings(max_examples=100)
    def test_requests_under_limit_pass_through(self, ip, path, request_count):
        """
        For any IP with requests at or under 100 in a window, requests
        should pass through normally (not receive 429).

        **Validates: Requirements 12.1, 24.1**
        """
        # Feature: financial-news-integration, Property 11: Rate limiting enforcement
        middleware = RateLimitMiddleware(self.get_response)

        mock_client = MagicMock()
        mock_client.incr.return_value = request_count
        middleware._redis_client = mock_client

        request = self.factory.get(path)
        request.META["REMOTE_ADDR"] = ip

        response = middleware(request)

        # Requests within the limit should pass through
        self.assertEqual(response.status_code, 200)
        self.get_response.assert_called_with(request)

    @given(
        ip=ipv4_strategy,
        path=api_paths,
        request_count=over_limit_counts,
    )
    @settings(max_examples=100)
    def test_rate_limit_response_body_contains_error_message(self, ip, path, request_count):
        """
        For any rate-limited response, the body should contain an error message.

        **Validates: Requirements 12.2, 24.2**
        """
        # Feature: financial-news-integration, Property 11: Rate limiting enforcement
        middleware = RateLimitMiddleware(self.get_response)

        mock_client = MagicMock()
        mock_client.incr.return_value = request_count
        middleware._redis_client = mock_client

        request = self.factory.get(path)
        request.META["REMOTE_ADDR"] = ip

        response = middleware(request)

        body = json.loads(response.content.decode("utf-8"))
        self.assertIn("error", body)
        self.assertIsInstance(body["error"], str)
        self.assertGreater(len(body["error"]), 0)


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 12: Security headers presence
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 12.6, 24.4


class PropertySecurityHeadersPresenceTest(TestCase):
    """
    Property 12: Security headers presence

    For any response from any API endpoint, the response headers should include
    X-Content-Type-Options: nosniff, X-Frame-Options: DENY, and
    Strict-Transport-Security with max-age >= 31536000.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def _build_middleware_chain(self, final_response):
        """
        Build the security-relevant middleware chain as configured in settings.py.

        SecurityMiddleware adds X-Content-Type-Options and Strict-Transport-Security.
        XFrameOptionsMiddleware adds X-Frame-Options.

        We test that these middleware produce the required security headers
        for all responses regardless of the endpoint or method.
        """
        from django.middleware.clickjacking import XFrameOptionsMiddleware
        from django.middleware.security import SecurityMiddleware

        # The innermost handler returns the final response
        def get_response(request):
            return final_response

        # Build chain from inside out:
        # XFrameOptionsMiddleware (inner) -> SecurityMiddleware (outer)
        xframe_middleware = XFrameOptionsMiddleware(get_response)
        security_middleware = SecurityMiddleware(xframe_middleware)
        return security_middleware

    @given(
        path=api_paths,
        method=http_methods,
        status_code=st.sampled_from([200, 201, 400, 404, 500]),
    )
    @settings(max_examples=100)
    @override_settings(
        SECURE_CONTENT_TYPE_NOSNIFF=True,
        SECURE_HSTS_SECONDS=31536000,
        X_FRAME_OPTIONS="DENY",
    )
    def test_security_headers_present_in_all_responses(self, path, method, status_code):
        """
        For any response from any API endpoint, security headers must be present.

        **Validates: Requirements 12.6, 24.4**
        """
        # Feature: financial-news-integration, Property 12: Security headers presence

        # Create a response with the given status code
        final_response = HttpResponse(
            json.dumps({"data": "test"}),
            status=status_code,
            content_type="application/json",
        )

        middleware = self._build_middleware_chain(final_response)

        # Create request with the given method
        # Use HTTPS to ensure HSTS header is set (SecurityMiddleware only sets
        # HSTS on secure requests, as per the HTTP spec)
        request_method = getattr(self.factory, method)
        request = request_method(path, secure=True)

        response = middleware(request)

        # X-Content-Type-Options: nosniff
        self.assertEqual(
            response.get("X-Content-Type-Options"),
            "nosniff",
            f"X-Content-Type-Options header missing or incorrect for {method.upper()} {path}",
        )

        # X-Frame-Options: DENY
        self.assertEqual(
            response.get("X-Frame-Options"),
            "DENY",
            f"X-Frame-Options header missing or incorrect for {method.upper()} {path}",
        )

        # Strict-Transport-Security with max-age >= 31536000
        hsts_header = response.get("Strict-Transport-Security", "")
        self.assertIn(
            "max-age=",
            hsts_header,
            f"Strict-Transport-Security header missing for {method.upper()} {path}",
        )
        # Extract max-age value and verify it's >= 31536000
        match = re.search(r"max-age=(\d+)", hsts_header)
        self.assertIsNotNone(match, "Could not parse max-age from HSTS header")
        max_age = int(match.group(1))
        self.assertGreaterEqual(
            max_age,
            31536000,
            f"HSTS max-age ({max_age}) is less than required 31536000",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 13: Error response safety
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 13.3, 13.4


class PropertyErrorResponseSafetyTest(TestCase):
    """
    Property 13: Error response safety

    For any error response (4xx or 5xx) from the API, the response body should
    never contain stack traces, internal hostnames, or configuration details,
    and should always include a correlation_id field containing a valid UUID v4 string.
    """

    def setUp(self):
        self.factory = RequestFactory()

    @given(
        path=api_paths,
        status_code=error_status_codes,
    )
    @settings(max_examples=100)
    def test_error_responses_contain_correlation_id(self, path, status_code):
        """
        For any error response, the body should include a correlation_id
        field containing a valid UUID v4 string.

        **Validates: Requirements 13.4**
        """
        # Feature: financial-news-integration, Property 13: Error response safety

        # Create a downstream response that returns an error
        error_body = json.dumps({"error": "Something went wrong"})
        downstream_response = HttpResponse(
            error_body,
            status=status_code,
            content_type="application/json",
        )

        def get_response(request):
            return downstream_response

        middleware = CorrelationIdMiddleware(get_response)

        request = self.factory.get(path)
        response = middleware(request)

        # Parse the response body
        body = json.loads(response.content.decode("utf-8"))

        # Must contain correlation_id
        self.assertIn(
            "correlation_id",
            body,
            f"Error response (HTTP {status_code}) missing correlation_id",
        )

        # correlation_id must be a valid UUID v4
        correlation_id = body["correlation_id"]
        try:
            parsed_uuid = uuid.UUID(correlation_id, version=4)
            self.assertEqual(str(parsed_uuid), correlation_id)
        except (ValueError, AttributeError):
            self.fail(
                f"correlation_id '{correlation_id}' is not a valid UUID v4"
            )

    @given(
        path=api_paths,
        unsafe_content=unsafe_content_fragments,
    )
    @settings(max_examples=100)
    def test_unhandled_exceptions_never_expose_internals(self, path, unsafe_content):
        """
        For any unhandled exception, the error response should never contain
        stack traces, internal hostnames, or configuration details.

        **Validates: Requirements 13.3**
        """
        # Feature: financial-news-integration, Property 13: Error response safety

        # Simulate an unhandled exception with potentially sensitive info
        def get_response(request):
            raise RuntimeError(unsafe_content)

        middleware = ErrorHandlingMiddleware(get_response)

        request = self.factory.get(path)
        # Ensure correlation_id is set (normally done by CorrelationIdMiddleware)
        request.correlation_id = str(uuid.uuid4())

        response = middleware(request)

        # Response should be 500
        self.assertEqual(response.status_code, 500)

        # Parse the response body
        body_str = response.content.decode("utf-8")
        body = json.loads(body_str)

        # The response body must NOT contain the unsafe content
        self.assertNotIn(
            unsafe_content,
            body_str,
            f"Error response exposed internal details: '{unsafe_content}'",
        )

        # Must not contain common stack trace patterns
        self.assertNotIn("Traceback", body_str)
        self.assertNotIn("File \"/", body_str)

        # Must contain correlation_id
        self.assertIn("correlation_id", body)

        # correlation_id must be a valid UUID v4
        correlation_id = body["correlation_id"]
        try:
            parsed_uuid = uuid.UUID(correlation_id, version=4)
            self.assertEqual(str(parsed_uuid), correlation_id)
        except (ValueError, AttributeError):
            self.fail(
                f"correlation_id '{correlation_id}' is not a valid UUID v4"
            )

    @given(
        path=api_paths,
        exception_suffix=st.text(
            alphabet=st.characters(
                whitelist_categories=("L",),
                min_codepoint=65,
                max_codepoint=90,
            ),
            min_size=5,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    def test_generic_error_message_for_all_exceptions(self, path, exception_suffix):
        """
        For any unhandled exception with arbitrary message content, the error
        response should contain only a generic message and correlation_id,
        never the original exception message.

        **Validates: Requirements 13.3, 13.4**
        """
        # Feature: financial-news-integration, Property 13: Error response safety

        # Use a unique prefix to ensure the exception message cannot be a
        # substring of the generic response fields
        exception_msg = f"SENSITIVE_ERROR_{exception_suffix}"

        def get_response(request):
            raise RuntimeError(exception_msg)

        middleware = ErrorHandlingMiddleware(get_response)

        request = self.factory.get(path)
        request.correlation_id = str(uuid.uuid4())

        response = middleware(request)

        # Response should be 500
        self.assertEqual(response.status_code, 500)

        body = json.loads(response.content.decode("utf-8"))

        # Must contain correlation_id
        self.assertIn("correlation_id", body)

        # Must contain the generic error message
        self.assertIn("error", body)
        generic_msg = "An internal server error occurred. Please try again later."
        self.assertEqual(body["error"], generic_msg)

        # The raw exception message must not leak into the response
        self.assertNotIn(
            exception_msg,
            response.content.decode("utf-8"),
            "Exception message leaked into error response",
        )
