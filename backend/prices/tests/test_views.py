"""Tests for the prices app views."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from prices.models import GoldPrice


class HistoricalPriceViewTest(TestCase):
    """Tests for GET /api/v1/prices/historical."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/v1/prices/historical"
        # Create sample price records
        today = date.today()
        for i in range(5):
            GoldPrice.objects.create(
                date=today - timedelta(days=i),
                open=Decimal("2000.00") + i,
                high=Decimal("2010.00") + i,
                low=Decimal("1990.00") + i,
                close=Decimal("2005.00") + i,
                volume=100000 + i * 1000,
            )

    @patch("prices.views._get_redis_client", return_value=None)
    def test_returns_200_with_default_date_range(self, mock_redis):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 5)

    @patch("prices.views._get_redis_client", return_value=None)
    def test_results_ordered_by_date_ascending(self, mock_redis):
        response = self.client.get(self.url)
        data = response.json()
        dates = [item["date"] for item in data]
        self.assertEqual(dates, sorted(dates))

    @patch("prices.views._get_redis_client", return_value=None)
    def test_filters_by_start_date(self, mock_redis):
        today = date.today()
        start = (today - timedelta(days=2)).isoformat()
        response = self.client.get(f"{self.url}?start_date={start}")
        data = response.json()
        self.assertEqual(len(data), 3)

    @patch("prices.views._get_redis_client", return_value=None)
    def test_filters_by_end_date(self, mock_redis):
        today = date.today()
        end = (today - timedelta(days=3)).isoformat()
        response = self.client.get(f"{self.url}?end_date={end}")
        data = response.json()
        self.assertEqual(len(data), 2)

    @patch("prices.views._get_redis_client", return_value=None)
    def test_filters_by_date_range(self, mock_redis):
        today = date.today()
        start = (today - timedelta(days=3)).isoformat()
        end = (today - timedelta(days=1)).isoformat()
        response = self.client.get(f"{self.url}?start_date={start}&end_date={end}")
        data = response.json()
        self.assertEqual(len(data), 3)

    @patch("prices.views._get_redis_client", return_value=None)
    def test_returns_400_for_invalid_start_date(self, mock_redis):
        response = self.client.get(f"{self.url}?start_date=not-a-date")
        self.assertEqual(response.status_code, 400)
        self.assertIn("start_date", response.json()["parameter"])

    @patch("prices.views._get_redis_client", return_value=None)
    def test_returns_400_for_invalid_end_date(self, mock_redis):
        response = self.client.get(f"{self.url}?end_date=2024-13-01")
        self.assertEqual(response.status_code, 400)
        self.assertIn("end_date", response.json()["parameter"])

    @patch("prices.views._get_redis_client", return_value=None)
    def test_returns_400_when_start_after_end(self, mock_redis):
        response = self.client.get(
            f"{self.url}?start_date=2024-06-01&end_date=2024-01-01"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("start_date", response.json()["parameter"])

    @patch("prices.views._get_redis_client", return_value=None)
    def test_returns_empty_array_for_no_records(self, mock_redis):
        response = self.client.get(
            f"{self.url}?start_date=2000-01-01&end_date=2000-01-31"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    @patch("prices.views._get_redis_client", return_value=None)
    def test_max_1095_records(self, mock_redis):
        """Verify the queryset is limited to 1095 records."""
        # Create more than 1095 records
        today = date.today()
        GoldPrice.objects.all().delete()
        records = []
        for i in range(1100):
            records.append(
                GoldPrice(
                    date=today - timedelta(days=i),
                    open=Decimal("2000.00"),
                    high=Decimal("2010.00"),
                    low=Decimal("1990.00"),
                    close=Decimal("2005.00"),
                    volume=100000,
                )
            )
        GoldPrice.objects.bulk_create(records)

        start = (today - timedelta(days=1200)).isoformat()
        response = self.client.get(f"{self.url}?start_date={start}")
        data = response.json()
        self.assertLessEqual(len(data), 1095)

    @patch("prices.views._get_redis_client", return_value=None)
    def test_response_fields(self, mock_redis):
        """Verify response contains expected fields."""
        response = self.client.get(self.url)
        data = response.json()
        self.assertGreater(len(data), 0)
        record = data[0]
        expected_fields = {"date", "open", "high", "low", "close", "volume"}
        self.assertEqual(set(record.keys()), expected_fields)
