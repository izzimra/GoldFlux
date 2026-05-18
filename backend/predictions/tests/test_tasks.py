"""Unit tests for predictions Celery tasks."""

import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from django.test import TestCase, override_settings

from predictions.models import ModelMetadata, Prediction
from predictions.tasks import (
    HOLDOUT_DAYS,
    MIN_TRAINING_DAYS,
    PREDICTION_DAYS,
    _should_activate_new_model,
    generate_predictions,
    train_model,
)
from prices.models import GoldPrice


def _create_price_records(count, start_date=None, base_price=2000.0):
    """Helper to create a set of GoldPrice records for testing."""
    if start_date is None:
        start_date = date.today() - timedelta(days=count + 100)

    records = []
    for i in range(count):
        record_date = start_date + timedelta(days=i)
        price = base_price + (i * 0.5)  # Slight upward trend
        records.append(
            GoldPrice(
                date=record_date,
                open=Decimal(str(round(price - 5, 2))),
                high=Decimal(str(round(price + 10, 2))),
                low=Decimal(str(round(price - 10, 2))),
                close=Decimal(str(round(price, 2))),
                volume=100000 + i * 100,
            )
        )
    GoldPrice.objects.bulk_create(records)
    return records


class TestTrainModelInsufficientData(TestCase):
    """Test train_model with insufficient data (<252 days)."""

    def test_insufficient_data_returns_error_status(self):
        """When fewer than 252 records exist, training should fail gracefully."""
        _create_price_records(100)

        result = train_model()

        assert result["status"] == "insufficient_data"
        assert result["records_available"] == 100
        assert result["minimum_required"] == MIN_TRAINING_DAYS

    def test_insufficient_data_no_model_created(self):
        """No ModelMetadata should be created when data is insufficient."""
        _create_price_records(200)

        train_model()

        assert ModelMetadata.objects.count() == 0


class TestTrainModelSuccess(TestCase):
    """Test train_model with sufficient data."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @override_settings(ML_MODELS_DIR=None)
    def test_successful_training_creates_metadata(self):
        """Successful training should create a ModelMetadata record."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_price_records(300)

            result = train_model()

            assert result["status"] == "success"
            assert ModelMetadata.objects.count() == 1

            metadata = ModelMetadata.objects.first()
            assert metadata.training_date == date.today()
            assert metadata.number_of_training_samples == 300 - HOLDOUT_DAYS
            assert metadata.is_active is True
            assert metadata.model_version == f"v{date.today().isoformat()}"
            assert metadata.mean_absolute_error > 0
            assert metadata.root_mean_squared_error > 0

    @override_settings(ML_MODELS_DIR=None)
    def test_successful_training_saves_model_artifact(self):
        """Successful training should save a .pkl file to the models directory."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_price_records(300)

            result = train_model()

            assert result["status"] == "success"
            expected_filename = f"model_v{date.today().isoformat()}.pkl"
            expected_path = self.models_dir / expected_filename
            assert expected_path.exists()

    @override_settings(ML_MODELS_DIR=None)
    def test_training_data_split_correctness(self):
        """Training should use correct split: last 63 as holdout, rest as training."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            total_records = 400
            _create_price_records(total_records)

            result = train_model()

            assert result["status"] == "success"
            assert result["training_samples"] == total_records - HOLDOUT_DAYS

    @override_settings(ML_MODELS_DIR=None)
    def test_first_model_is_activated(self):
        """When no previous model exists, the new model should be activated."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_price_records(300)

            result = train_model()

            assert result["is_active"] is True
            metadata = ModelMetadata.objects.first()
            assert metadata.is_active is True


class TestModelComparison(TestCase):
    """Test model comparison logic."""

    def test_no_active_model_activates_new(self):
        """When no active model exists, new model should be activated."""
        assert _should_activate_new_model(50.0) is True

    def test_new_model_within_threshold_activates(self):
        """When new MAE is within 10% of active, new model should be activated."""
        ModelMetadata.objects.create(
            training_date=date.today() - timedelta(days=1),
            mean_absolute_error=Decimal("50.0000"),
            root_mean_squared_error=Decimal("60.0000"),
            number_of_training_samples=200,
            model_version="v2024-01-01",
            is_active=True,
        )

        # New MAE of 54 is within 10% of 50 (threshold = 55)
        assert _should_activate_new_model(54.0) is True

    def test_new_model_exceeds_threshold_not_activated(self):
        """When new MAE exceeds active by >10%, current model is retained."""
        ModelMetadata.objects.create(
            training_date=date.today() - timedelta(days=1),
            mean_absolute_error=Decimal("50.0000"),
            root_mean_squared_error=Decimal("60.0000"),
            number_of_training_samples=200,
            model_version="v2024-01-01",
            is_active=True,
        )

        # New MAE of 56 exceeds 10% of 50 (threshold = 55)
        assert _should_activate_new_model(56.0) is False

    def test_new_model_exactly_at_threshold_activates(self):
        """When new MAE is exactly at 10% threshold, model should be activated."""
        ModelMetadata.objects.create(
            training_date=date.today() - timedelta(days=1),
            mean_absolute_error=Decimal("50.0000"),
            root_mean_squared_error=Decimal("60.0000"),
            number_of_training_samples=200,
            model_version="v2024-01-01",
            is_active=True,
        )

        # New MAE of 55 is exactly at 10% threshold (50 * 1.1 = 55)
        assert _should_activate_new_model(55.0) is True


class TestTrainModelDeactivatesPrevious(TestCase):
    """Test that training deactivates previous active model when new one is better."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @override_settings(ML_MODELS_DIR=None)
    def test_previous_model_deactivated_on_new_activation(self):
        """When a new model is activated, the previous active model is deactivated."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            # Create a previous active model with high MAE so new one will be better
            old_model = ModelMetadata.objects.create(
                training_date=date.today() - timedelta(days=30),
                mean_absolute_error=Decimal("9999.0000"),
                root_mean_squared_error=Decimal("9999.0000"),
                number_of_training_samples=200,
                model_version="v2024-01-01",
                is_active=True,
            )

            _create_price_records(300)
            result = train_model()

            assert result["status"] == "success"
            assert result["is_active"] is True

            old_model.refresh_from_db()
            assert old_model.is_active is False

            new_model = ModelMetadata.objects.get(
                model_version=f"v{date.today().isoformat()}"
            )
            assert new_model.is_active is True


class TestTrainModelRuntimeException(TestCase):
    """Test train_model handles runtime exceptions gracefully."""

    @patch("predictions.tasks.GoldPrice.objects")
    def test_runtime_exception_returns_error(self, mock_objects):
        """Runtime exceptions should be caught and logged."""
        mock_objects.order_by.side_effect = RuntimeError("Database connection lost")

        result = train_model()

        assert result["status"] == "error"
        assert "Database connection lost" in result["error"]

    @patch("predictions.tasks.GoldPrice.objects")
    def test_runtime_exception_retains_previous_model(self, mock_objects):
        """Runtime exceptions should not affect existing active model."""
        active_model = ModelMetadata.objects.create(
            training_date=date.today() - timedelta(days=1),
            mean_absolute_error=Decimal("50.0000"),
            root_mean_squared_error=Decimal("60.0000"),
            number_of_training_samples=200,
            model_version="v2024-01-01",
            is_active=True,
        )

        mock_objects.order_by.side_effect = RuntimeError("Unexpected error")

        train_model()

        active_model.refresh_from_db()
        assert active_model.is_active is True


# ──────────────────────────────────────────────────────────────────────────────
# Tests for generate_predictions task
# ──────────────────────────────────────────────────────────────────────────────


def _create_active_model_with_artifact(models_dir):
    """Helper to create an active model metadata and a mock model artifact."""
    import joblib
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import PolynomialFeatures, StandardScaler

    model_version = f"v{date.today().isoformat()}"

    # Create model metadata
    metadata = ModelMetadata.objects.create(
        training_date=date.today(),
        mean_absolute_error=Decimal("15.0000"),
        root_mean_squared_error=Decimal("20.0000"),
        number_of_training_samples=300,
        model_version=model_version,
        is_active=True,
    )

    # Create and save a real model artifact
    models_dir.mkdir(parents=True, exist_ok=True)
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("poly", PolynomialFeatures(degree=3, include_bias=False)),
        ("ridge", Ridge(alpha=1.0)),
    ])

    # Train on some dummy data so it can predict
    X_train = np.array([d.toordinal() for d in [
        date.today() - timedelta(days=i) for i in range(100, 0, -1)
    ]]).reshape(-1, 1)
    y_train = np.array([2000.0 + i * 0.5 for i in range(100)])
    model.fit(X_train, y_train)

    filepath = models_dir / f"model_{model_version}.pkl"
    joblib.dump(model, filepath)

    return metadata, model_version


class TestGeneratePredictionsNoModel(TestCase):
    """Test generate_predictions when no active model exists."""

    def test_no_active_model_returns_empty(self):
        """When no active model exists, should return empty prediction set."""
        result = generate_predictions()

        assert result["status"] == "no_model"
        assert result["predictions_generated"] == 0
        assert Prediction.objects.count() == 0

    def test_inactive_model_only_returns_empty(self):
        """When only inactive models exist, should return empty prediction set."""
        ModelMetadata.objects.create(
            training_date=date.today(),
            mean_absolute_error=Decimal("15.0000"),
            root_mean_squared_error=Decimal("20.0000"),
            number_of_training_samples=300,
            model_version="v2024-01-01",
            is_active=False,
        )

        result = generate_predictions()

        assert result["status"] == "no_model"
        assert result["predictions_generated"] == 0


class TestGeneratePredictionsMissingArtifact(TestCase):
    """Test generate_predictions when model artifact is missing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_artifact_returns_empty(self):
        """When model artifact file doesn't exist, should return empty set."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            ModelMetadata.objects.create(
                training_date=date.today(),
                mean_absolute_error=Decimal("15.0000"),
                root_mean_squared_error=Decimal("20.0000"),
                number_of_training_samples=300,
                model_version="v2024-01-01",
                is_active=True,
            )

            result = generate_predictions()

            assert result["status"] == "model_load_failed"
            assert result["predictions_generated"] == 0
            assert Prediction.objects.count() == 0


class TestGeneratePredictionsSuccess(TestCase):
    """Test generate_predictions with a valid model."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generates_30_predictions(self):
        """Should generate exactly 30 prediction records."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            result = generate_predictions()

            assert result["status"] == "success"
            assert result["predictions_generated"] == PREDICTION_DAYS
            assert Prediction.objects.count() == PREDICTION_DAYS

    def test_predictions_cover_next_30_days(self):
        """Predictions should cover the next 30 calendar days."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            generate_predictions()

            predictions = Prediction.objects.order_by("predicted_date")
            today = date.today()

            for i, pred in enumerate(predictions):
                expected_date = today + timedelta(days=i + 1)
                assert pred.predicted_date == expected_date

    def test_predicted_close_price_rounded_to_2_decimals(self):
        """Predicted close prices should be rounded to 2 decimal places."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            generate_predictions()

            for pred in Prediction.objects.all():
                # DecimalField with decimal_places=2 ensures this
                price_str = str(pred.predicted_close_price)
                if "." in price_str:
                    decimal_part = price_str.split(".")[1]
                    assert len(decimal_part) <= 2

    def test_confidence_interval_constraint(self):
        """CI lower should always be <= CI upper."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            generate_predictions()

            for pred in Prediction.objects.all():
                assert pred.confidence_interval_lower <= pred.confidence_interval_upper

    def test_generation_timestamp_set(self):
        """All predictions should have a generation_timestamp set."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            generate_predictions()

            for pred in Prediction.objects.all():
                assert pred.generation_timestamp is not None


class TestGeneratePredictionsReplacement(TestCase):
    """Test that generate_predictions replaces existing predictions correctly."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_replaces_future_predictions(self):
        """Should replace existing predictions with predicted_date > generation_timestamp."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            # Create some existing future predictions
            today = date.today()
            for i in range(10):
                Prediction.objects.create(
                    predicted_date=today + timedelta(days=i + 1),
                    predicted_close_price=Decimal("1999.99"),
                    confidence_interval_lower=Decimal("1900.00"),
                    confidence_interval_upper=Decimal("2100.00"),
                    generation_timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                )

            generate_predictions()

            # Should have exactly 30 predictions (old ones replaced)
            assert Prediction.objects.count() == PREDICTION_DAYS

            # None should have the old price
            assert not Prediction.objects.filter(
                predicted_close_price=Decimal("1999.99")
            ).exists()

    def test_retains_past_predictions(self):
        """Should not delete predictions with predicted_date <= generation date."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            # Create a past prediction (before today)
            past_date = date.today() - timedelta(days=5)
            Prediction.objects.create(
                predicted_date=past_date,
                predicted_close_price=Decimal("1888.88"),
                confidence_interval_lower=Decimal("1800.00"),
                confidence_interval_upper=Decimal("1900.00"),
                generation_timestamp=datetime.now(timezone.utc) - timedelta(days=10),
            )

            generate_predictions()

            # Past prediction should still exist
            assert Prediction.objects.filter(predicted_date=past_date).exists()
            # Total should be 30 new + 1 past
            assert Prediction.objects.count() == PREDICTION_DAYS + 1


class TestGeneratePredictionsPartialSet(TestCase):
    """Test that partial prediction sets are discarded."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("predictions.tasks._generate_prediction_records")
    def test_partial_set_discarded(self, mock_generate):
        """When fewer than 30 predictions are generated, discard and retain previous."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            # Create existing predictions
            today = date.today()
            for i in range(5):
                Prediction.objects.create(
                    predicted_date=today + timedelta(days=i + 1),
                    predicted_close_price=Decimal("2000.00"),
                    confidence_interval_lower=Decimal("1900.00"),
                    confidence_interval_upper=Decimal("2100.00"),
                    generation_timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                )

            # Mock to return only 20 predictions (partial set)
            mock_generate.return_value = [
                {
                    "predicted_date": today + timedelta(days=i + 1),
                    "predicted_close_price": Decimal("2050.00"),
                    "confidence_interval_lower": Decimal("1950.00"),
                    "confidence_interval_upper": Decimal("2150.00"),
                    "generation_timestamp": datetime.now(timezone.utc),
                }
                for i in range(20)
            ]

            result = generate_predictions()

            assert result["status"] == "partial_set_discarded"
            # Previous predictions should be retained
            assert Prediction.objects.count() == 5
            assert Prediction.objects.filter(
                predicted_close_price=Decimal("2000.00")
            ).count() == 5


class TestGeneratePredictionsCacheInvalidation(TestCase):
    """Test that prediction cache is invalidated on success."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("predictions.tasks._invalidate_prediction_cache")
    def test_cache_invalidated_on_success(self, mock_invalidate):
        """Cache should be invalidated after successful prediction generation."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            result = generate_predictions()

            assert result["status"] == "success"
            mock_invalidate.assert_called_once()

    @patch("predictions.tasks._invalidate_prediction_cache")
    @patch("predictions.tasks._generate_prediction_records")
    def test_cache_not_invalidated_on_partial_set(
        self, mock_generate, mock_invalidate
    ):
        """Cache should NOT be invalidated when partial set is discarded."""
        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_active_model_with_artifact(self.models_dir)

            today = date.today()
            mock_generate.return_value = [
                {
                    "predicted_date": today + timedelta(days=i + 1),
                    "predicted_close_price": Decimal("2050.00"),
                    "confidence_interval_lower": Decimal("1950.00"),
                    "confidence_interval_upper": Decimal("2150.00"),
                    "generation_timestamp": datetime.now(timezone.utc),
                }
                for i in range(20)
            ]

            result = generate_predictions()

            assert result["status"] == "partial_set_discarded"
            mock_invalidate.assert_not_called()
