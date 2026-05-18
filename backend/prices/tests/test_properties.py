"""
Property-based tests for data ingestion pipeline.

Uses Hypothesis to validate universal properties of the gold price
data ingestion, upsert, and filtering logic.
"""

import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from prices.models import GoldPrice
from prices.tasks import ingest_gold_prices


# ──────────────────────────────────────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────────────────────────────────────

# Valid price values: positive decimals with 2 decimal places
# Gold prices typically range from ~200 to ~3000+ USD
price_strategy = st.decimals(
    min_value=Decimal("1.00"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)

# Valid volume values: positive integers
volume_strategy = st.integers(min_value=0, max_value=10**12)

# Valid dates within a reasonable range for gold price data
date_strategy = st.dates(
    min_value=datetime.date(2000, 1, 1),
    max_value=datetime.date(2030, 12, 31),
)


# Strategy for a complete, valid gold price record
def gold_price_record_strategy():
    """Generate a valid gold price record as a dict matching yfinance output."""
    return st.fixed_dictionaries({
        "Date": date_strategy.map(lambda d: pd.Timestamp(d)),
        "Open": price_strategy.map(float),
        "High": price_strategy.map(float),
        "Low": price_strategy.map(float),
        "Close": price_strategy.map(float),
        "Volume": volume_strategy,
    })


# Strategy for records that may have null fields
def nullable_field_strategy():
    """Generate a value that is either a valid float or None/NaN."""
    return st.one_of(
        st.just(None),
        st.just(float("nan")),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 1: Price record upsert round-trip and idempotence
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 1.2, 1.3


class PropertyPriceRecordUpsertRoundTripTest(TestCase):
    """
    Property 1: Price record upsert round-trip and idempotence

    For any valid Gold_Price_Record, storing it in the database and then
    retrieving it by date should return a record with identical field values.
    Furthermore, for any record inserted twice with the same date, the database
    should contain exactly one record for that date with the values from the
    most recent insert.
    """

    @given(record=gold_price_record_strategy())
    @settings(max_examples=100)
    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_upsert_round_trip_preserves_field_values(
        self, mock_ticker_cls, mock_invalidate, record
    ):
        """
        For any valid Gold_Price_Record, storing it via the ingestion pipeline
        and retrieving it by date should return identical field values.

        **Validates: Requirements 1.2**
        """
        # Feature: financial-news-integration, Property 1: Price record upsert round-trip and idempotence

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame([record])

        result = ingest_gold_prices()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["records_processed"], 1)
        self.assertEqual(result["records_skipped"], 0)

        # Retrieve the record by date
        record_date = record["Date"].date()
        stored = GoldPrice.objects.get(date=record_date)

        # Verify all fields match (values are rounded to 2 decimal places)
        self.assertEqual(stored.date, record_date)
        self.assertEqual(stored.open, Decimal(str(round(record["Open"], 2))))
        self.assertEqual(stored.high, Decimal(str(round(record["High"], 2))))
        self.assertEqual(stored.low, Decimal(str(round(record["Low"], 2))))
        self.assertEqual(stored.close, Decimal(str(round(record["Close"], 2))))
        self.assertEqual(stored.volume, int(record["Volume"]))

    @given(
        record1=gold_price_record_strategy(),
        record2=gold_price_record_strategy(),
    )
    @settings(max_examples=100)
    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_upsert_idempotence_same_date(
        self, mock_ticker_cls, mock_invalidate, record1, record2
    ):
        """
        For any record inserted twice with the same date, the database should
        contain exactly one record for that date with the values from the most
        recent insert.

        **Validates: Requirements 1.3**
        """
        # Feature: financial-news-integration, Property 1: Price record upsert round-trip and idempotence

        # Force both records to have the same date
        shared_date = record1["Date"]
        record2 = dict(record2)
        record2["Date"] = shared_date

        # First insert
        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame([record1])

        ingest_gold_prices()

        # Second insert with same date but potentially different values
        mock_ticker.history.return_value = pd.DataFrame([record2])

        ingest_gold_prices()

        # Should have exactly one record for this date
        record_date = shared_date.date()
        count = GoldPrice.objects.filter(date=record_date).count()
        self.assertEqual(
            count,
            1,
            f"Expected exactly 1 record for date {record_date}, found {count}",
        )

        # The stored record should have the values from the second insert
        stored = GoldPrice.objects.get(date=record_date)
        self.assertEqual(stored.open, Decimal(str(round(record2["Open"], 2))))
        self.assertEqual(stored.high, Decimal(str(round(record2["High"], 2))))
        self.assertEqual(stored.low, Decimal(str(round(record2["Low"], 2))))
        self.assertEqual(stored.close, Decimal(str(round(record2["Close"], 2))))
        self.assertEqual(stored.volume, int(record2["Volume"]))


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 2: Incomplete record filtering
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 1.6


class PropertyIncompleteRecordFilteringTest(TestCase):
    """
    Property 2: Incomplete record filtering

    For any set of price records where some records have null or missing values
    in required fields, the ingestion pipeline should store only the records
    with all fields present, and the count of skipped records should equal the
    number of records with any null field.
    """

    @given(
        valid_records=st.lists(
            gold_price_record_strategy(),
            min_size=1,
            max_size=5,
        ),
        null_field_choices=st.lists(
            st.sampled_from(["Open", "High", "Low", "Close", "Volume"]),
            min_size=1,
            max_size=5,
        ),
    )
    @settings(max_examples=100)
    @patch("prices.tasks._invalidate_historical_cache")
    @patch("prices.tasks.yf.Ticker")
    def test_incomplete_records_are_filtered(
        self, mock_ticker_cls, mock_invalidate, valid_records, null_field_choices
    ):
        """
        For any set of price records where some have null fields, the ingestion
        pipeline should store only complete records and report the correct
        number of skipped records.

        **Validates: Requirements 1.6**
        """
        # Feature: financial-news-integration, Property 2: Incomplete record filtering

        # Ensure all valid records have unique dates
        used_dates = set()
        unique_valid_records = []
        for rec in valid_records:
            rec_date = rec["Date"].date()
            if rec_date not in used_dates:
                used_dates.add(rec_date)
                unique_valid_records.append(rec)

        assume(len(unique_valid_records) >= 1)

        # Create incomplete records with null fields, using different dates
        incomplete_records = []
        base_date = datetime.date(1990, 1, 1)
        for i, null_field in enumerate(null_field_choices):
            # Use a date that won't collide with valid records
            inc_date = base_date + datetime.timedelta(days=i)
            while inc_date in used_dates:
                inc_date += datetime.timedelta(days=1)
            used_dates.add(inc_date)

            incomplete_record = {
                "Date": pd.Timestamp(inc_date),
                "Open": 2050.0,
                "High": 2060.0,
                "Low": 2040.0,
                "Close": 2055.0,
                "Volume": 100000,
            }
            # Set the chosen field to None or NaN
            if null_field == "Volume":
                incomplete_record[null_field] = None
            else:
                incomplete_record[null_field] = float("nan")
            incomplete_records.append(incomplete_record)

        # Combine valid and incomplete records
        all_records = unique_valid_records + incomplete_records

        mock_ticker = MagicMock()
        mock_ticker_cls.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame(all_records)

        result = ingest_gold_prices()

        expected_processed = len(unique_valid_records)
        expected_skipped = len(incomplete_records)

        self.assertEqual(result["status"], "success")
        self.assertEqual(
            result["records_processed"],
            expected_processed,
            f"Expected {expected_processed} processed records, got {result['records_processed']}",
        )
        self.assertEqual(
            result["records_skipped"],
            expected_skipped,
            f"Expected {expected_skipped} skipped records, got {result['records_skipped']}",
        )

        # Verify only valid records are in the database
        self.assertEqual(GoldPrice.objects.count(), expected_processed)

        # Verify each valid record is stored correctly
        for rec in unique_valid_records:
            rec_date = rec["Date"].date()
            self.assertTrue(
                GoldPrice.objects.filter(date=rec_date).exists(),
                f"Valid record for date {rec_date} was not stored",
            )

        # Verify no incomplete records are stored
        for inc_rec in incomplete_records:
            inc_date = inc_rec["Date"].date()
            self.assertFalse(
                GoldPrice.objects.filter(date=inc_date).exists(),
                f"Incomplete record for date {inc_date} should not be stored",
            )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 7: Historical API response correctness
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 5.1, 5.2


class PropertyHistoricalAPIResponseCorrectnessTest(TestCase):
    """
    Property 7: Historical API response correctness

    For any GET request to /api/v1/prices/historical with valid date parameters,
    the response should contain only Gold_Price_Records with dates within the
    requested range (inclusive), ordered by date ascending, with a maximum of
    1095 records.
    """

    @given(
        num_records=st.integers(min_value=1, max_value=50),
        range_offset_start=st.integers(min_value=0, max_value=30),
        range_offset_end=st.integers(min_value=0, max_value=30),
    )
    @settings(max_examples=100)
    @patch("prices.views._get_redis_client", return_value=None)
    def test_response_contains_only_records_within_date_range(
        self, mock_redis, num_records, range_offset_start, range_offset_end
    ):
        """
        For any GET request with valid date parameters, the response should
        contain only Gold_Price_Records with dates within the requested range
        (inclusive), ordered by date ascending.

        **Validates: Requirements 5.1, 5.2**
        """
        # Feature: financial-news-integration, Property 7: Historical API response correctness
        from rest_framework.test import APIClient

        client = APIClient()

        # Create records spanning a date range
        base_date = datetime.date(2023, 1, 1)
        records = []
        for i in range(num_records):
            record_date = base_date + datetime.timedelta(days=i)
            records.append(
                GoldPrice(
                    date=record_date,
                    open=Decimal("2000.00"),
                    high=Decimal("2010.00"),
                    low=Decimal("1990.00"),
                    close=Decimal("2005.00"),
                    volume=100000 + i,
                )
            )
        GoldPrice.objects.bulk_create(records)

        # Define query range that may be a subset of the records
        start_date = base_date + datetime.timedelta(days=range_offset_start)
        end_date = base_date + datetime.timedelta(days=num_records - 1 - range_offset_end)

        # Only test valid ranges where start <= end
        assume(start_date <= end_date)

        response = client.get(
            "/api/v1/prices/historical",
            {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )

        self.assertEqual(response.status_code, 200)

        data = response.json()

        # Verify all returned records are within the requested range (inclusive)
        for record in data:
            record_date = datetime.date.fromisoformat(record["date"])
            self.assertGreaterEqual(
                record_date,
                start_date,
                f"Record date {record_date} is before start_date {start_date}",
            )
            self.assertLessEqual(
                record_date,
                end_date,
                f"Record date {record_date} is after end_date {end_date}",
            )

        # Verify ordering is ascending by date
        dates = [record["date"] for record in data]
        self.assertEqual(
            dates,
            sorted(dates),
            "Records should be ordered by date ascending",
        )

        # Verify maximum of 1095 records
        self.assertLessEqual(
            len(data),
            1095,
            f"Response contains {len(data)} records, exceeding max of 1095",
        )

        # Verify all records in the range are returned (since we have < 1095)
        expected_count = sum(
            1
            for r in records
            if start_date <= r.date <= end_date
        )
        self.assertEqual(
            len(data),
            expected_count,
            f"Expected {expected_count} records in range, got {len(data)}",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 8: API input validation
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 5.6, 5.7, 12.5


class PropertyAPIInputValidationTest(TestCase):
    """
    Property 8: API input validation

    For any request with date parameters where start_date is after end_date,
    or where date parameters are not in ISO 8601 (YYYY-MM-DD) format, the API
    should return HTTP 400 with a descriptive error message.
    """

    @given(
        start_offset=st.integers(min_value=1, max_value=365),
    )
    @settings(max_examples=100)
    @patch("prices.views._get_redis_client", return_value=None)
    def test_start_date_after_end_date_returns_400(self, mock_redis, start_offset):
        """
        For any request where start_date is after end_date, the API should
        return HTTP 400 with a descriptive error message.

        **Validates: Requirements 5.6**
        """
        # Feature: financial-news-integration, Property 8: API input validation
        from rest_framework.test import APIClient

        client = APIClient()

        # Create dates where start > end
        end_date = datetime.date(2023, 6, 15)
        start_date = end_date + datetime.timedelta(days=start_offset)

        response = client.get(
            "/api/v1/prices/historical",
            {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )

        self.assertEqual(
            response.status_code,
            400,
            f"Expected 400 when start_date ({start_date}) > end_date ({end_date}), "
            f"got {response.status_code}",
        )

        # Verify error message is descriptive
        data = response.json()
        self.assertIn(
            "error",
            data,
            "Error response should contain an 'error' field",
        )
        self.assertTrue(
            len(data["error"]) > 0,
            "Error message should be non-empty",
        )

    @given(
        invalid_date=st.one_of(
            # Random strings that are not valid dates
            st.text(min_size=1, max_size=20).filter(
                lambda s: not _is_valid_date_format(s)
            ),
            # Dates with wrong separators
            st.from_regex(r"\d{4}/\d{2}/\d{2}", fullmatch=True),
            # Dates with wrong format (DD-MM-YYYY)
            st.from_regex(r"\d{2}-\d{2}-\d{4}", fullmatch=True),
            # Partial dates
            st.from_regex(r"\d{4}-\d{2}", fullmatch=True),
        ),
        param_name=st.sampled_from(["start_date", "end_date"]),
    )
    @settings(max_examples=100)
    @patch("prices.views._get_redis_client", return_value=None)
    def test_invalid_date_format_returns_400(self, mock_redis, invalid_date, param_name):
        """
        For any request where date parameters are not in ISO 8601 (YYYY-MM-DD)
        format, the API should return HTTP 400 with a descriptive error message.

        **Validates: Requirements 5.7**
        """
        # Feature: financial-news-integration, Property 8: API input validation
        from rest_framework.test import APIClient

        client = APIClient()

        params = {param_name: invalid_date}
        # Provide a valid value for the other param to isolate the test
        if param_name == "start_date":
            params["end_date"] = "2023-12-31"
        else:
            params["start_date"] = "2023-01-01"

        response = client.get("/api/v1/prices/historical", params)

        self.assertEqual(
            response.status_code,
            400,
            f"Expected 400 for invalid {param_name}='{invalid_date}', "
            f"got {response.status_code}",
        )

        # Verify error message is descriptive
        data = response.json()
        self.assertIn(
            "error",
            data,
            "Error response should contain an 'error' field",
        )
        self.assertTrue(
            len(data["error"]) > 0,
            "Error message should be non-empty and descriptive",
        )


def _is_valid_date_format(s: str) -> bool:
    """Check if a string is a valid YYYY-MM-DD date."""
    try:
        parts = s.split("-")
        if len(parts) != 3:
            return False
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        datetime.date(year, month, day)
        return True
    except (ValueError, TypeError):
        return False
