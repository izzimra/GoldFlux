"""Tests for predictions app views."""

from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from predictions.models import ModelMetadata


class ModelMetadataViewTest(TestCase):
    """Tests for GET /api/v1/model/metadata endpoint."""

    def setUp(self):
        self.client = APIClient()
        self.url = "/api/v1/model/metadata"

    def test_returns_404_when_no_model_trained(self):
        """Should return 404 with error message when no model metadata exists."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())
        self.assertEqual(
            response.json()["error"], "No trained model is available"
        )

    def test_returns_latest_model_metadata(self):
        """Should return the most recent model metadata by training_date."""
        # Create older model
        ModelMetadata.objects.create(
            training_date=date(2024, 1, 10),
            mean_absolute_error=Decimal("15.5000"),
            root_mean_squared_error=Decimal("20.3000"),
            number_of_training_samples=1000,
            model_version="v2024-01-10",
            is_active=False,
        )
        # Create newer model (should be returned)
        ModelMetadata.objects.create(
            training_date=date(2024, 1, 15),
            mean_absolute_error=Decimal("12.4500"),
            root_mean_squared_error=Decimal("18.7200"),
            number_of_training_samples=1257,
            model_version="v2024-01-15",
            is_active=True,
        )

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["training_date"], "2024-01-15T00:00:00Z")
        self.assertEqual(float(data["mean_absolute_error"]), 12.45)
        self.assertEqual(float(data["root_mean_squared_error"]), 18.72)
        self.assertEqual(data["number_of_training_samples"], 1257)
        self.assertEqual(data["model_version"], "v2024-01-15")

    def test_response_contains_all_required_fields(self):
        """Should include all required fields in the response."""
        ModelMetadata.objects.create(
            training_date=date(2024, 1, 15),
            mean_absolute_error=Decimal("12.4500"),
            root_mean_squared_error=Decimal("18.7200"),
            number_of_training_samples=1257,
            model_version="v2024-01-15",
            is_active=True,
        )

        response = self.client.get(self.url)
        data = response.json()

        required_fields = [
            "training_date",
            "mean_absolute_error",
            "root_mean_squared_error",
            "number_of_training_samples",
            "model_version",
        ]
        for field in required_fields:
            self.assertIn(field, data)

    def test_training_date_in_iso_8601_format(self):
        """Should return training_date in ISO 8601 format."""
        ModelMetadata.objects.create(
            training_date=date(2024, 3, 20),
            mean_absolute_error=Decimal("10.0000"),
            root_mean_squared_error=Decimal("15.0000"),
            number_of_training_samples=500,
            model_version="v2024-03-20",
            is_active=True,
        )

        response = self.client.get(self.url)
        data = response.json()

        # ISO 8601 format check
        self.assertEqual(data["training_date"], "2024-03-20T00:00:00Z")
