"""Unit tests for the ingest_gold_prices Celery task."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
from django.test import TestCase, override_settings

from prices.models import GoldPrice
from prices.tasks import ingest_gold_prices, _invalidate_historical_cache


class IngestGoldPricesTaskTest(TestCase):
    """Tests for the ingest_gold_prices task."""

    def _make_dataframe(self, records):
        """Helper to create a DataFrame mimicking yfinance output."""
        return pd.DataFrame(records)

    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_successful_ingestion(self, mock_ticker_cls, mock_invalidate):
        """Test that valid records are upserted correctly."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = self._make_dataframe([
            {
                "Date": pd.Timestamp("2024-01-15"),
                "Open": 2050.0,
                "High": 2060.0,
                "Low": 2040.0,
                "Close": 2055.0,
                "Volume": 100000,
            },
            {
                "Date": pd.Timestamp("2024-01-16"),
                "Open": 2055.0,
                "High": 2070.0,
                "Low": 2050.0,
                "Close": 2065.0,
                "Volume": 120000,
            },
        ])

        result = ingest_gold_prices()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["records_processed"], 2)
        self.assertEqual(result["records_skipped"], 0)
        self.assertEqual(GoldPrice.objects.count(), 2)

        record = GoldPrice.objects.get(date=date(2024, 1, 15))
        self.assertEqual(record.open, Decimal("2050.00"))
        self.assertEqual(record.close, Decimal("2055.00"))
        self.assertEqual(record.volume, 100000)

        mock_invalidate.assert_called_once()

    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_skips_records_with_null_fields(self, mock_ticker_cls, mock_invalidate):
        """Test that records with null/NaN fields are skipped."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = self._make_dataframe([
            {
                "Date": pd.Timestamp("2024-01-15"),
                "Open": 2050.0,
                "High": 2060.0,
                "Low": 2040.0,
                "Close": 2055.0,
                "Volume": 100000,
            },
            {
                "Date": pd.Timestamp("2024-01-16"),
                "Open": None,
                "High": 2070.0,
                "Low": 2050.0,
                "Close": 2065.0,
                "Volume": 120000,
            },
            {
                "Date": pd.Timestamp("2024-01-17"),
                "Open": 2060.0,
                "High": float("nan"),
                "Low": 2050.0,
                "Close": 2065.0,
                "Volume": 120000,
            },
        ])

        result = ingest_gold_prices()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["records_processed"], 1)
        self.assertEqual(result["records_skipped"], 2)
        self.assertEqual(GoldPrice.objects.count(), 1)

    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_upsert_updates_existing_record(self, mock_ticker_cls, mock_invalidate):
        """Test that duplicate dates update existing records."""
        # Create an existing record
        GoldPrice.objects.create(
            date=date(2024, 1, 15),
            open=Decimal("2000.00"),
            high=Decimal("2010.00"),
            low=Decimal("1990.00"),
            close=Decimal("2005.00"),
            volume=50000,
        )

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = self._make_dataframe([
            {
                "Date": pd.Timestamp("2024-01-15"),
                "Open": 2050.0,
                "High": 2060.0,
                "Low": 2040.0,
                "Close": 2055.0,
                "Volume": 100000,
            },
        ])

        result = ingest_gold_prices()

        self.assertEqual(result["records_processed"], 1)
        self.assertEqual(GoldPrice.objects.count(), 1)

        record = GoldPrice.objects.get(date=date(2024, 1, 15))
        self.assertEqual(record.open, Decimal("2050.00"))
        self.assertEqual(record.close, Decimal("2055.00"))
        self.assertEqual(record.volume, 100000)

    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_empty_dataframe_returns_no_data(self, mock_ticker_cls, mock_invalidate):
        """Test handling of empty response from yfinance."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame()

        result = ingest_gold_prices()

        self.assertEqual(result["status"], "no_data")
        self.assertEqual(result["records_processed"], 0)
        self.assertEqual(GoldPrice.objects.count(), 0)
        mock_invalidate.assert_not_called()

    @patch("prices.tasks.yf.Ticker")
    def test_yfinance_exception_raises_for_retry(self, mock_ticker_cls):
        """Test that yfinance exceptions propagate for Celery retry."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.side_effect = ConnectionError("Network error")

        with self.assertRaises(ConnectionError):
            ingest_gold_prices()

    @patch("prices.tasks.redis.from_url")
    @override_settings(REDIS_URL="redis://localhost:6379/0")
    def test_invalidate_cache_success(self, mock_redis_from_url):
        """Test successful cache invalidation."""
        mock_redis = MagicMock()
        mock_redis_from_url.return_value = mock_redis
        mock_redis.keys.return_value = [b"cache:historical:abc123"]

        _invalidate_historical_cache()

        mock_redis.keys.assert_called_once_with("cache:historical:*")
        mock_redis.delete.assert_called_once_with(b"cache:historical:abc123")

    @patch("prices.tasks.redis.from_url")
    @override_settings(REDIS_URL="redis://localhost:6379/0")
    def test_invalidate_cache_redis_error_handled(self, mock_redis_from_url):
        """Test that Redis errors during cache invalidation are handled gracefully."""
        import redis as redis_lib

        mock_redis_from_url.side_effect = redis_lib.RedisError("Connection refused")

        # Should not raise
        _invalidate_historical_cache()

    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_logs_ingestion_timestamp(self, mock_ticker_cls, mock_invalidate):
        """Test that the result includes a valid timestamp."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = self._make_dataframe([
            {
                "Date": pd.Timestamp("2024-01-15"),
                "Open": 2050.0,
                "High": 2060.0,
                "Low": 2040.0,
                "Close": 2055.0,
                "Volume": 100000,
            },
        ])

        result = ingest_gold_prices()

        self.assertIn("timestamp", result)
        # Verify it's a valid ISO timestamp
        ts = datetime.fromisoformat(result["timestamp"])
        self.assertIsNotNone(ts)

    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_skips_record_with_null_volume(self, mock_ticker_cls, mock_invalidate):
        """Test that records with null volume are skipped."""
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = self._make_dataframe([
            {
                "Date": pd.Timestamp("2024-01-15"),
                "Open": 2050.0,
                "High": 2060.0,
                "Low": 2040.0,
                "Close": 2055.0,
                "Volume": None,
            },
        ])

        result = ingest_gold_prices()

        self.assertEqual(result["records_skipped"], 1)
        self.assertEqual(result["records_processed"], 0)
