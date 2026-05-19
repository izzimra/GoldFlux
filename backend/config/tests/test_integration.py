"""Integration tests for the GoldFlux full pipeline.

Covers Task 16.4 from the financial-news-integration spec:
    - Data ingestion → training → prediction flow
    - News fetch → parse → cache → serve flow
    - Cache invalidation on data refresh
    - Redis failover behavior (bypass cache, serve from DB)
    - Rate limiting across all endpoints

External dependencies (yfinance, Marketaux HTTP API, Redis) are mocked. The
tests run inside a Django test database and mock the network boundary so they
do not hit real external services.

Validates Requirements: 8.3, 8.4, 8.7, 8.8, 12.1, 16.1, 16.4
"""

import json
import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pandas as pd
import redis as redis_lib
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from config.middleware import RateLimitMiddleware
from news.services import NEWS_CACHE_KEY, NEWS_LAST_UPDATED_KEY
from predictions.models import ModelMetadata, Prediction
from prices.models import GoldPrice


# ──────────────────────────────────────────────────────────────────────────────
# In-memory Redis double for integration tests
# ──────────────────────────────────────────────────────────────────────────────


class FakeRedis:
    """Minimal in-memory Redis double covering the ops used by the project.

    Supports the subset needed for caching, cache invalidation, rate limiting
    and the news cache pipeline:
        - get / set / setex / delete / keys / incr / expire / ping / pipeline
    """

    def __init__(self):
        self._data: dict[str, str] = {}
        # Only used for assertion purposes. TTL expiry is not simulated because
        # the tests run synchronously and do not rely on real-time expiry.
        self._ttl: dict[str, int] = {}

    # ── Core key/value ops ────────────────────────────────────────────────
    def set(self, key, value, ex=None):
        self._data[key] = value
        if ex is not None:
            self._ttl[key] = ex
        return True

    def setex(self, key, ttl, value):
        self._data[key] = value
        self._ttl[key] = ttl
        return True

    def get(self, key):
        return self._data.get(key)

    def delete(self, *keys):
        count = 0
        for key in keys:
            if key in self._data:
                del self._data[key]
                self._ttl.pop(key, None)
                count += 1
        return count

    def keys(self, pattern):
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in self._data if k.startswith(prefix)]
        return [k for k in self._data if k == pattern]

    # ── Counter ops ───────────────────────────────────────────────────────
    def incr(self, key):
        current = int(self._data.get(key, 0)) + 1
        self._data[key] = str(current)
        return current

    def expire(self, key, ttl):
        self._ttl[key] = ttl
        return 1

    def ping(self):
        return True

    # ── Pipeline support ──────────────────────────────────────────────────
    def pipeline(self):
        return _FakePipeline(self)


class _FakePipeline:
    """Minimal Redis pipeline supporting set/get/execute used by NewsCacheService."""

    def __init__(self, parent):
        self._parent = parent
        self._ops = []

    def set(self, key, value, ex=None):
        self._ops.append(("set", key, value, ex))
        return self

    def get(self, key):
        self._ops.append(("get", key))
        return self

    def execute(self):
        results = []
        for op in self._ops:
            if op[0] == "set":
                self._parent.set(op[1], op[2], ex=op[3])
                results.append(True)
            elif op[0] == "get":
                results.append(self._parent.get(op[1]))
        self._ops.clear()
        return results


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_yfinance_dataframe(num_records: int, base_date: date | None = None):
    """Produce a DataFrame shaped like yfinance's Ticker.history() output."""
    if base_date is None:
        base_date = date.today() - timedelta(days=num_records)
    rows = []
    for i in range(num_records):
        d = base_date + timedelta(days=i)
        price = 2000.0 + i * 0.5
        rows.append(
            {
                "Date": pd.Timestamp(d),
                "Open": price - 5,
                "High": price + 10,
                "Low": price - 10,
                "Close": price,
                "Volume": 100_000 + i * 100,
            }
        )
    return pd.DataFrame(rows)


def _build_marketaux_response(articles: list[dict]) -> MagicMock:
    """Build a MagicMock requests.Response object for Marketaux."""
    response = MagicMock()
    response.status_code = 200
    response.text = json.dumps({"data": articles})
    response.json.return_value = {"data": articles}
    response.raise_for_status.return_value = None
    return response


def _sample_marketaux_articles() -> list[dict]:
    """Two well-formed Marketaux articles with sentiment entities."""
    return [
        {
            "title": "Gold rallies on inflation data",
            "source": "Reuters",
            "url": "https://reuters.example.com/gold-rally",
            "published_at": "2024-01-15T12:00:00Z",
            "description": "Gold prices climbed today as inflation data fuelled demand.",
            "entities": [{"sentiment_score": 0.6}],
        },
        {
            "title": "Gold drops on stronger dollar",
            "source": "Bloomberg",
            "url": "https://bloomberg.example.com/gold-drop",
            "published_at": "2024-01-15T10:00:00Z",
            "description": "Gold edged lower as the U.S. dollar strengthened.",
            "entities": [{"sentiment_score": -0.5}],
        },
    ]


def _seed_active_model(models_dir: Path) -> ModelMetadata:
    """Train a tiny scikit-learn pipeline and persist it as the active model."""
    import joblib
    import numpy as np
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import PolynomialFeatures, StandardScaler

    model_version = f"v{date.today().isoformat()}"
    metadata = ModelMetadata.objects.create(
        training_date=date.today(),
        mean_absolute_error=Decimal("15.0000"),
        root_mean_squared_error=Decimal("20.0000"),
        number_of_training_samples=300,
        model_version=model_version,
        is_active=True,
    )
    models_dir.mkdir(parents=True, exist_ok=True)
    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            ("poly", PolynomialFeatures(degree=2, include_bias=False)),
            ("ridge", Ridge(alpha=1.0)),
        ]
    )
    today = date.today()
    X = np.array(
        [(today - timedelta(days=i)).toordinal() for i in range(100, 0, -1)]
    ).reshape(-1, 1)
    y = np.array([2000.0 + i * 0.5 for i in range(100)])
    pipeline.fit(X, y)
    joblib.dump(pipeline, models_dir / f"model_{model_version}.pkl")
    return metadata


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Full data pipeline (ingestion → training → prediction)
# ──────────────────────────────────────────────────────────────────────────────


class FullDataPipelineIntegrationTest(TestCase):
    """Validates the data ingestion → training → prediction flow.

    Mocks yfinance and Redis. Runs each stage of the pipeline in sequence and
    asserts that the database reflects the expected state after each step.

    Validates Requirements: 8.3, 8.4
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"
        self.fake_redis = FakeRedis()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("predictions.tasks.redis.from_url")
    @patch("prices.tasks.redis.from_url")
    @patch("prices.tasks.yf.Ticker")
    def test_pipeline_runs_end_to_end(
        self, mock_ticker_cls, mock_prices_redis, mock_predictions_redis
    ):
        from predictions.tasks import generate_predictions, train_model
        from prices.tasks import ingest_gold_prices

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_yfinance_dataframe(300)

        mock_prices_redis.return_value = self.fake_redis
        mock_predictions_redis.return_value = self.fake_redis

        with override_settings(ML_MODELS_DIR=self.models_dir):
            # Stage 1 — Ingestion
            ingest_result = ingest_gold_prices()
            self.assertEqual(ingest_result["status"], "success")
            self.assertEqual(ingest_result["records_processed"], 300)
            self.assertEqual(GoldPrice.objects.count(), 300)

            # Stage 2 — Training
            train_result = train_model()
            self.assertEqual(train_result["status"], "success")
            self.assertEqual(ModelMetadata.objects.count(), 1)
            metadata = ModelMetadata.objects.first()
            self.assertTrue(metadata.is_active)

            # Stage 3 — Prediction generation
            pred_result = generate_predictions()
            self.assertEqual(pred_result["status"], "success")
            self.assertEqual(pred_result["predictions_generated"], 30)
            self.assertEqual(Prediction.objects.count(), 30)

            # Sanity: predictions are in chronological order and start tomorrow
            predictions = list(Prediction.objects.order_by("predicted_date"))
            today = date.today()
            for i, pred in enumerate(predictions):
                self.assertEqual(pred.predicted_date, today + timedelta(days=i + 1))
                self.assertLessEqual(
                    pred.confidence_interval_lower, pred.confidence_interval_upper
                )


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: News fetch → parse → cache → serve flow
# ──────────────────────────────────────────────────────────────────────────────


class NewsFetchToServeIntegrationTest(TestCase):
    """Validates the news pipeline: HTTP fetch → parse → Redis cache → API serve.

    Mocks the Marketaux HTTP boundary and Redis. After running the fetch_news
    Celery task, the GET /api/v1/news/gold/ endpoint should serve the freshly
    cached articles.
    """

    def setUp(self):
        self.client = APIClient()
        self.fake_redis = FakeRedis()

    @patch("config.middleware.RateLimitMiddleware.redis_client", new_callable=PropertyMock)
    @patch("news.services.redis.Redis.from_url")
    @patch("news.services.requests.get")
    def test_fetch_then_serve_returns_cached_articles(
        self, mock_requests_get, mock_news_redis, mock_middleware_redis
    ):
        # Marketaux returns two well-formed articles
        mock_requests_get.return_value = _build_marketaux_response(
            _sample_marketaux_articles()
        )
        # Both NewsCacheService and MarketauxClient share the same fake Redis
        mock_news_redis.return_value = self.fake_redis
        # Rate limit middleware uses the fake Redis to keep requests under limit
        mock_middleware_redis.return_value = self.fake_redis

        # Run the news task — this should populate the news cache.
        # MarketauxClient reads NEWS_API_KEY from os.environ, but requests.get
        # is mocked so the key value is irrelevant for this test.
        from news.tasks import fetch_news

        fetch_news()

        # Cache should be populated under the canonical key
        self.assertIn(NEWS_CACHE_KEY, self.fake_redis._data)
        self.assertIn(NEWS_LAST_UPDATED_KEY, self.fake_redis._data)
        cached = json.loads(self.fake_redis._data[NEWS_CACHE_KEY])
        self.assertEqual(len(cached), 2)

        # Serve via HTTP — articles should appear sorted by published_at desc
        response = self.client.get("/api/v1/news/gold/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("articles", body)
        self.assertIn("last_updated", body)
        self.assertEqual(len(body["articles"]), 2)

        titles = [a["title"] for a in body["articles"]]
        self.assertIn("Gold rallies on inflation data", titles)
        self.assertIn("Gold drops on stronger dollar", titles)

        # Sentiment labels should derive from scores
        positive = next(a for a in body["articles"] if "rallies" in a["title"])
        negative = next(a for a in body["articles"] if "drops" in a["title"])
        self.assertEqual(positive["sentiment_label"], "positive")
        self.assertEqual(negative["sentiment_label"], "negative")

    @patch("config.middleware.RateLimitMiddleware.redis_client", new_callable=PropertyMock)
    @patch("news.services.redis.Redis.from_url")
    @patch("news.services.requests.get")
    def test_fetch_strips_html_before_serving(
        self, mock_requests_get, mock_news_redis, mock_middleware_redis
    ):
        """HTML and script tags from upstream payloads must not survive to the API."""
        articles = [
            {
                "title": "<b>Gold</b> surges<script>alert('xss')</script>",
                "source": "<em>Reuters</em>",
                "url": "https://reuters.example.com/gold",
                "published_at": "2024-01-15T12:00:00Z",
                "description": "<p>Gold prices climbed</p> sharply.",
                "entities": [{"sentiment_score": 0.4}],
            }
        ]
        mock_requests_get.return_value = _build_marketaux_response(articles)
        mock_news_redis.return_value = self.fake_redis
        mock_middleware_redis.return_value = self.fake_redis

        from news.tasks import fetch_news

        fetch_news()

        response = self.client.get("/api/v1/news/gold/")
        self.assertEqual(response.status_code, 200)
        article = response.json()["articles"][0]
        self.assertNotIn("<", article["title"])
        self.assertNotIn("script", article["title"].lower())
        self.assertNotIn("<", article["description"])
        self.assertNotIn("<", article["source_name"])


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Cache invalidation on data refresh
# ──────────────────────────────────────────────────────────────────────────────


class CacheInvalidationIntegrationTest(TestCase):
    """Validates cache invalidation triggered by pipeline completion.

    - Successful ingestion drops cached historical price entries.
    - Successful prediction generation drops cached prediction entries.

    Validates Requirements: 8.3, 8.4
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"
        self.fake_redis = FakeRedis()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("prices.tasks.redis.from_url")
    @patch("prices.tasks.yf.Ticker")
    def test_ingestion_invalidates_historical_price_cache(
        self, mock_ticker_cls, mock_prices_redis
    ):
        from prices.tasks import ingest_gold_prices

        # Pre-populate two historical price cache entries that match the pattern
        self.fake_redis.set("cache:historical:abc123", json.dumps([{"date": "2024-01-01"}]))
        self.fake_redis.set("cache:historical:def456", json.dumps([{"date": "2024-01-02"}]))
        # And one unrelated key that must survive
        self.fake_redis.set("cache:predictions:other", "should-remain")

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = _make_yfinance_dataframe(5)
        mock_prices_redis.return_value = self.fake_redis

        result = ingest_gold_prices()
        self.assertEqual(result["status"], "success")

        # Historical entries gone, unrelated key remains
        self.assertNotIn("cache:historical:abc123", self.fake_redis._data)
        self.assertNotIn("cache:historical:def456", self.fake_redis._data)
        self.assertIn("cache:predictions:other", self.fake_redis._data)

    @patch("predictions.tasks.redis.from_url")
    def test_prediction_generation_invalidates_prediction_cache(
        self, mock_predictions_redis
    ):
        from predictions.tasks import generate_predictions

        # Pre-populate prediction cache entries plus an unrelated key
        self.fake_redis.set(
            "cache:predictions:hash1", json.dumps({"data": [], "message": "old"})
        )
        self.fake_redis.set("cache:predictions:hash2", json.dumps({"data": []}))
        self.fake_redis.set("cache:historical:other", "should-remain")
        mock_predictions_redis.return_value = self.fake_redis

        with override_settings(ML_MODELS_DIR=self.models_dir):
            _seed_active_model(self.models_dir)
            result = generate_predictions()

        self.assertEqual(result["status"], "success")
        self.assertNotIn("cache:predictions:hash1", self.fake_redis._data)
        self.assertNotIn("cache:predictions:hash2", self.fake_redis._data)
        self.assertIn("cache:historical:other", self.fake_redis._data)


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Redis failover behavior (bypass cache, serve from DB)
# ──────────────────────────────────────────────────────────────────────────────


class RedisFailoverIntegrationTest(TestCase):
    """Validates that API endpoints continue serving when Redis is unreachable.

    Validates Requirements: 8.7, 8.8
    """

    def setUp(self):
        self.client = APIClient()
        # Seed some data so the DB has content to serve
        today = date.today()
        for i in range(3):
            GoldPrice.objects.create(
                date=today - timedelta(days=i),
                open=Decimal("2000.00"),
                high=Decimal("2010.00"),
                low=Decimal("1990.00"),
                close=Decimal("2005.00"),
                volume=100_000,
            )
        Prediction.objects.create(
            predicted_date=today + timedelta(days=1),
            predicted_close_price=Decimal("2050.00"),
            confidence_interval_lower=Decimal("1950.00"),
            confidence_interval_upper=Decimal("2150.00"),
            generation_timestamp=datetime.now(timezone.utc),
        )
        ModelMetadata.objects.create(
            training_date=today,
            mean_absolute_error=Decimal("15.0000"),
            root_mean_squared_error=Decimal("20.0000"),
            number_of_training_samples=200,
            model_version="v2024-01-01",
            is_active=True,
        )

    @patch("config.middleware.RateLimitMiddleware.redis_client", new_callable=PropertyMock)
    @patch("prices.views._get_redis_client")
    def test_historical_prices_served_when_redis_down(
        self, mock_redis_client, mock_middleware_redis
    ):
        # Views helper returns None when Redis is unreachable
        mock_redis_client.return_value = None
        # Rate limit middleware also returns None (so it bypasses)
        mock_middleware_redis.return_value = None

        response = self.client.get("/api/v1/prices/historical")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 3)

    @patch("config.middleware.RateLimitMiddleware.redis_client", new_callable=PropertyMock)
    @patch("predictions.views._get_redis_client")
    def test_predictions_served_when_redis_down(
        self, mock_redis_client, mock_middleware_redis
    ):
        mock_redis_client.return_value = None
        mock_middleware_redis.return_value = None

        response = self.client.get("/api/v1/prices/predictions")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        # PredictionListView returns a raw list when records exist
        self.assertEqual(len(body), 1)
        self.assertEqual(str(body[0]["predicted_close_price"]), "2050.00")

    @patch("config.middleware.RateLimitMiddleware.redis_client", new_callable=PropertyMock)
    @patch("news.views.NewsCacheService")
    def test_news_endpoint_handles_redis_failure_gracefully(
        self, mock_cache_cls, mock_middleware_redis
    ):
        # Cache service raises Redis errors when accessed
        mock_cache = MagicMock()
        mock_cache.get_cached_articles.side_effect = redis_lib.RedisError(
            "Connection refused"
        )
        mock_cache_cls.return_value = mock_cache
        mock_middleware_redis.return_value = None

        response = self.client.get("/api/v1/news/gold/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["articles"], [])
        self.assertEqual(body["message"], "news is temporarily unavailable")


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Rate limiting across all endpoints
# ──────────────────────────────────────────────────────────────────────────────


@override_settings(ALLOWED_HOSTS=["*"])
class RateLimitingIntegrationTest(TestCase):
    """Verifies the RateLimitMiddleware enforces 100 req/60s on every endpoint.

    Validates Requirements: 12.1, 16.1
    """

    ENDPOINTS = [
        "/api/v1/prices/historical",
        "/api/v1/prices/predictions",
        "/api/v1/model/metadata",
        "/api/v1/news/gold/",
    ]

    def setUp(self):
        self.client = APIClient()
        # Seed minimal data so endpoints don't 404 / 503
        today = date.today()
        GoldPrice.objects.create(
            date=today,
            open=Decimal("2000.00"),
            high=Decimal("2010.00"),
            low=Decimal("1990.00"),
            close=Decimal("2005.00"),
            volume=100_000,
        )
        ModelMetadata.objects.create(
            training_date=today,
            mean_absolute_error=Decimal("15.0000"),
            root_mean_squared_error=Decimal("20.0000"),
            number_of_training_samples=200,
            model_version="v2024-01-01",
            is_active=True,
        )

    def _patch_middleware_redis(self, fake_client):
        return patch.object(
            RateLimitMiddleware,
            "redis_client",
            new_callable=PropertyMock,
            return_value=fake_client,
        )

    def test_request_under_limit_passes_for_each_endpoint(self):
        fake = FakeRedis()
        with self._patch_middleware_redis(fake), \
             patch("prices.views._get_redis_client", return_value=None), \
             patch("predictions.views._get_redis_client", return_value=None), \
             patch("news.views.NewsCacheService") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get_cached_articles.return_value = ([], None)
            mock_cache_cls.return_value = mock_cache

            for endpoint in self.ENDPOINTS:
                response = self.client.get(endpoint)
                self.assertNotEqual(
                    response.status_code, 429,
                    f"Endpoint {endpoint} unexpectedly rate-limited at low volume",
                )

    def test_request_over_limit_returns_429_with_retry_after(self):
        """The 101st request from the same IP within a window must be 429."""
        # Pre-load the fake counter so the next incr returns 101
        fake = FakeRedis()

        # Compute the same key the middleware will use for this request
        # The middleware uses: ratelimit:{ip}:{window}.
        # To make the assertion deterministic we don't predict the window —
        # we instead override `incr` to always return values >100.
        class OverLimitRedis(FakeRedis):
            def incr(self, key):
                # Always over the limit
                return 101

        with self._patch_middleware_redis(OverLimitRedis()), \
             patch("prices.views._get_redis_client", return_value=None), \
             patch("predictions.views._get_redis_client", return_value=None), \
             patch("news.views.NewsCacheService") as mock_cache_cls:
            mock_cache = MagicMock()
            mock_cache.get_cached_articles.return_value = ([], None)
            mock_cache_cls.return_value = mock_cache

            for endpoint in self.ENDPOINTS:
                response = self.client.get(endpoint)
                self.assertEqual(
                    response.status_code, 429,
                    f"Endpoint {endpoint} should be rate-limited when counter > 100",
                )
                self.assertIn("Retry-After", response)
                retry_after = int(response["Retry-After"])
                self.assertGreaterEqual(retry_after, 1)
                self.assertLessEqual(retry_after, 60)

    def test_rate_limit_keys_are_per_ip(self):
        """Two distinct IPs must each get their own rate-limit budget."""
        fake = FakeRedis()
        seen_keys: set[str] = set()

        original_incr = fake.incr

        def tracking_incr(key):
            seen_keys.add(key)
            return original_incr(key)

        fake.incr = tracking_incr  # type: ignore[assignment]

        with self._patch_middleware_redis(fake), \
             patch("prices.views._get_redis_client", return_value=None):
            self.client.get(
                "/api/v1/prices/historical", REMOTE_ADDR="10.0.0.1"
            )
            self.client.get(
                "/api/v1/prices/historical", REMOTE_ADDR="10.0.0.2"
            )

        # We must have keys for both IPs (window suffix may vary between calls
        # but the IP segment of the key should differ).
        ips_seen = {key.split(":")[1] for key in seen_keys}
        self.assertIn("10.0.0.1", ips_seen)
        self.assertIn("10.0.0.2", ips_seen)
