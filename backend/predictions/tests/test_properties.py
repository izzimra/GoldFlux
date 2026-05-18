"""
Property-based tests for ML training pipeline and prediction generation.

Uses Hypothesis to validate universal properties of the ML model
training data split logic, model comparison threshold logic,
prediction generation correctness, and prediction replacement atomicity.
"""

import shutil
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from django.test import override_settings

from predictions.models import ModelMetadata, Prediction
from predictions.tasks import (
    HOLDOUT_DAYS,
    MIN_TRAINING_DAYS,
    PREDICTION_DAYS,
    MAE_DEGRADATION_THRESHOLD,
    train_model,
    generate_predictions,
    _should_activate_new_model,
    _generate_prediction_records,
    _replace_predictions,
)
from prices.models import GoldPrice


# ──────────────────────────────────────────────────────────────────────────────
# Strategies
# ──────────────────────────────────────────────────────────────────────────────

# Number of records: must be more than MIN_TRAINING_DAYS (252)
# Keep upper bound reasonable to avoid slow tests
record_count_strategy = st.integers(
    min_value=MIN_TRAINING_DAYS + 1,
    max_value=600,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _create_price_records(count, start_date=None, base_price=2000.0, price_increment=0.5):
    """Helper to create a set of GoldPrice records for testing."""
    if start_date is None:
        start_date = date.today() - timedelta(days=count + 100)

    records = []
    for i in range(count):
        record_date = start_date + timedelta(days=i)
        price = base_price + (i * price_increment)
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


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 3: Training data split correctness
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 3.2


class PropertyTrainingDataSplitCorrectnessTest(TestCase):
    """
    Property 3: Training data split correctness

    For any dataset of Gold_Price_Records with more than 252 records, the ML
    training pipeline should always reserve exactly the most recent 63 trading
    days as the holdout test set, with all prior records used as the training set.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @given(total_records=record_count_strategy)
    @settings(max_examples=100)
    def test_training_split_reserves_exact_holdout_days(self, total_records):
        """
        For any dataset with more than 252 records, the training pipeline
        should always use exactly (total - 63) records for training and
        reserve the most recent 63 as holdout.

        **Validates: Requirements 3.2**
        """
        # Feature: financial-news-integration, Property 3: Training data split correctness

        with self.settings(ML_MODELS_DIR=self.models_dir):
            _create_price_records(total_records)

            result = train_model()

            # Training should succeed
            self.assertEqual(
                result["status"],
                "success",
                f"Expected success with {total_records} records, got: {result}",
            )

            # The number of training samples should be total - HOLDOUT_DAYS
            expected_training_samples = total_records - HOLDOUT_DAYS
            self.assertEqual(
                result["training_samples"],
                expected_training_samples,
                f"With {total_records} total records, expected "
                f"{expected_training_samples} training samples (total - {HOLDOUT_DAYS}), "
                f"but got {result['training_samples']}",
            )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 4: Model comparison threshold logic
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 3.5


# Strategies for Property 4
# Active model MAE: positive decimals representing realistic error values
active_mae_strategy = st.floats(
    min_value=1.0, max_value=500.0, allow_nan=False, allow_infinity=False
)

# Degradation factor: how much worse the new model is relative to active
# Values > 0.10 mean the new model exceeds the threshold
degradation_factor_strategy = st.floats(
    min_value=-0.5, max_value=1.0, allow_nan=False, allow_infinity=False
)


class PropertyModelComparisonThresholdLogicTest(TestCase):
    """
    Property 4: Model comparison threshold logic

    For any newly trained model and existing active model, if the new model's
    mean_absolute_error exceeds the active model's mean_absolute_error by more
    than 10%, then the active flag should remain on the existing model and the
    new model should be stored with is_active=false.
    """

    @given(
        active_mae=active_mae_strategy,
        degradation_factor=degradation_factor_strategy,
    )
    @settings(max_examples=100)
    def test_model_comparison_threshold_logic(self, active_mae, degradation_factor):
        """
        For any active model MAE and new model MAE, if the new MAE exceeds
        the active MAE by more than 10%, _should_activate_new_model returns False.
        Otherwise, it returns True.

        **Validates: Requirements 3.5**
        """
        # Feature: financial-news-integration, Property 4: Model comparison threshold logic

        # The implementation stores MAE rounded to 4 decimal places in the DB
        stored_mae = round(active_mae, 4)

        # Create an active model with the given MAE
        ModelMetadata.objects.create(
            training_date=date.today() - timedelta(days=1),
            mean_absolute_error=Decimal(str(stored_mae)),
            root_mean_squared_error=Decimal(str(round(active_mae * 1.2, 4))),
            number_of_training_samples=300,
            model_version="v2024-01-01",
            is_active=True,
        )

        # Compute new MAE based on degradation factor
        new_mae = active_mae * (1 + degradation_factor)

        # The implementation reads the stored (rounded) MAE back as float
        # and computes threshold from that value. We must mirror this logic.
        db_active_mae = float(Decimal(str(stored_mae)))
        threshold = db_active_mae * (1 + MAE_DEGRADATION_THRESHOLD)

        # The implementation uses strict > comparison: new_mae > threshold means NOT activated
        expected_activate = not (new_mae > threshold)

        # Call the function under test
        result = _should_activate_new_model(new_mae)

        self.assertEqual(
            result,
            expected_activate,
            f"With active_mae={active_mae:.4f}, stored_mae={stored_mae:.4f}, "
            f"new_mae={new_mae:.4f}, threshold={threshold:.4f}, "
            f"expected activate={expected_activate}, got {result}",
        )

    @given(new_mae=st.floats(min_value=0.1, max_value=500.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100)
    def test_no_active_model_always_activates(self, new_mae):
        """
        When no active model exists, any new model should be activated
        regardless of its MAE.

        **Validates: Requirements 3.5**
        """
        # Feature: financial-news-integration, Property 4: Model comparison threshold logic

        # Ensure no active model exists
        ModelMetadata.objects.filter(is_active=True).delete()

        result = _should_activate_new_model(new_mae)

        self.assertTrue(
            result,
            f"With no active model, expected new model to be activated "
            f"regardless of MAE ({new_mae:.4f}), but got False",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 5: Prediction generation correctness
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 4.1, 4.2, 15.7


class PropertyPredictionGenerationCorrectnessTest(TestCase):
    """
    Property 5: Prediction generation correctness

    For any successful model training run, the prediction engine should generate
    exactly 30 Prediction_Records covering the next 30 calendar days, each with
    predicted_close_price rounded to 2 decimal places and
    confidence_interval_lower <= confidence_interval_upper.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @given(
        base_price=st.floats(
            min_value=500.0, max_value=5000.0, allow_nan=False, allow_infinity=False
        ),
        price_increment=st.floats(
            min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False
        ),
    )
    @settings(max_examples=100)
    def test_prediction_generation_produces_30_records(self, base_price, price_increment):
        """
        For any successful model training, the prediction engine generates
        exactly 30 Prediction_Records covering the next 30 calendar days.

        **Validates: Requirements 4.1, 4.2, 15.7**
        """
        # Feature: financial-news-integration, Property 5: Prediction generation correctness

        with self.settings(ML_MODELS_DIR=self.models_dir):
            # Create sufficient price records for training
            total_records = MIN_TRAINING_DAYS + HOLDOUT_DAYS + 10
            _create_price_records(
                total_records, base_price=base_price, price_increment=price_increment
            )

            # Train the model first
            train_result = train_model()
            assume(train_result["status"] == "success")

            # Generate predictions
            result = generate_predictions()

            # Verify success
            self.assertEqual(
                result["status"],
                "success",
                f"Expected prediction generation to succeed, got: {result}",
            )

            # Verify exactly 30 predictions were generated
            self.assertEqual(
                result["predictions_generated"],
                PREDICTION_DAYS,
                f"Expected {PREDICTION_DAYS} predictions, got {result['predictions_generated']}",
            )

            # Verify predictions in database
            predictions = Prediction.objects.all().order_by("predicted_date")
            self.assertEqual(predictions.count(), PREDICTION_DAYS)

            # Verify predictions cover the next 30 calendar days
            today = date.today()
            expected_dates = [today + timedelta(days=i + 1) for i in range(PREDICTION_DAYS)]

            for i, pred in enumerate(predictions):
                # Each prediction covers the next 30 calendar days
                self.assertEqual(
                    pred.predicted_date,
                    expected_dates[i],
                    f"Prediction {i} date mismatch: expected {expected_dates[i]}, "
                    f"got {pred.predicted_date}",
                )

                # predicted_close_price rounded to 2 decimal places
                price_str = str(pred.predicted_close_price)
                if "." in price_str:
                    decimal_places = len(price_str.split(".")[1])
                    self.assertLessEqual(
                        decimal_places,
                        2,
                        f"Prediction {i} price {pred.predicted_close_price} "
                        f"has more than 2 decimal places",
                    )

                # confidence_interval_lower <= confidence_interval_upper
                self.assertLessEqual(
                    pred.confidence_interval_lower,
                    pred.confidence_interval_upper,
                    f"Prediction {i}: CI lower ({pred.confidence_interval_lower}) "
                    f"> CI upper ({pred.confidence_interval_upper})",
                )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 6: Prediction replacement atomicity
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 4.3, 4.6


class PropertyPredictionReplacementAtomicityTest(TestCase):
    """
    Property 6: Prediction replacement atomicity

    For any new prediction generation, all existing Prediction_Records with
    predicted_date later than the generation timestamp should be replaced.
    If generation produces fewer than 30 records, the partial set should be
    discarded and previous predictions retained unchanged.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.models_dir = Path(self.temp_dir) / "models"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @given(
        num_existing_predictions=st.integers(min_value=1, max_value=30),
        days_offset=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=100)
    def test_prediction_replacement_replaces_future_predictions(
        self, num_existing_predictions, days_offset
    ):
        """
        For any new prediction generation, all existing Prediction_Records
        with predicted_date later than the generation timestamp should be replaced.

        **Validates: Requirements 4.3, 4.6**
        """
        # Feature: financial-news-integration, Property 6: Prediction replacement atomicity

        with self.settings(ML_MODELS_DIR=self.models_dir):
            generation_timestamp = datetime.now(timezone.utc)
            today = generation_timestamp.date()

            # Create existing predictions (some in the future relative to generation)
            existing_predictions = []
            for i in range(num_existing_predictions):
                pred_date = today + timedelta(days=i + 1 + days_offset)
                existing_predictions.append(
                    Prediction(
                        predicted_date=pred_date,
                        predicted_close_price=Decimal("2000.00"),
                        confidence_interval_lower=Decimal("1950.00"),
                        confidence_interval_upper=Decimal("2050.00"),
                        generation_timestamp=generation_timestamp - timedelta(hours=24),
                    )
                )
            Prediction.objects.bulk_create(existing_predictions)

            # Create new predictions to replace
            new_predictions = []
            for i in range(PREDICTION_DAYS):
                pred_date = today + timedelta(days=i + 1)
                new_predictions.append({
                    "predicted_date": pred_date,
                    "predicted_close_price": Decimal("2100.00"),
                    "confidence_interval_lower": Decimal("2050.00"),
                    "confidence_interval_upper": Decimal("2150.00"),
                    "generation_timestamp": generation_timestamp,
                })

            # Replace predictions
            _replace_predictions(new_predictions, generation_timestamp)

            # Verify: all predictions in DB should be the new ones
            all_predictions = Prediction.objects.filter(
                predicted_date__gt=today
            ).order_by("predicted_date")

            # The new predictions should be present
            new_pred_dates = {today + timedelta(days=i + 1) for i in range(PREDICTION_DAYS)}
            db_pred_dates = {p.predicted_date for p in all_predictions}

            # All new prediction dates should be in the database
            for new_date in new_pred_dates:
                self.assertIn(
                    new_date,
                    db_pred_dates,
                    f"Expected new prediction date {new_date} to be in database",
                )

            # All new predictions should have the new generation_timestamp
            for pred in all_predictions:
                if pred.predicted_date in new_pred_dates:
                    self.assertEqual(
                        pred.predicted_close_price,
                        Decimal("2100.00"),
                        f"Prediction for {pred.predicted_date} was not replaced",
                    )

    @given(
        partial_count=st.integers(min_value=1, max_value=PREDICTION_DAYS - 1),
    )
    @settings(max_examples=100)
    def test_partial_set_discarded_retains_previous(self, partial_count):
        """
        If generation produces fewer than 30 records, the partial set should
        be discarded and previous predictions retained unchanged.

        **Validates: Requirements 4.3, 4.6**
        """
        # Feature: financial-news-integration, Property 6: Prediction replacement atomicity

        with self.settings(ML_MODELS_DIR=self.models_dir):
            generation_timestamp = datetime.now(timezone.utc)
            today = generation_timestamp.date()

            # Create existing predictions that should be retained
            existing_predictions = []
            for i in range(PREDICTION_DAYS):
                pred_date = today + timedelta(days=i + 1)
                existing_predictions.append(
                    Prediction(
                        predicted_date=pred_date,
                        predicted_close_price=Decimal("2000.00"),
                        confidence_interval_lower=Decimal("1950.00"),
                        confidence_interval_upper=Decimal("2050.00"),
                        generation_timestamp=generation_timestamp - timedelta(hours=24),
                    )
                )
            Prediction.objects.bulk_create(existing_predictions)

            original_count = Prediction.objects.count()
            original_prices = list(
                Prediction.objects.order_by("predicted_date").values_list(
                    "predicted_close_price", flat=True
                )
            )

            # Create a mock model that produces fewer than 30 predictions
            mock_model = MagicMock()
            mock_model.predict.return_value = np.array(
                [2100.0] * partial_count
            )

            # Create an active model metadata
            ModelMetadata.objects.create(
                training_date=today,
                mean_absolute_error=Decimal("10.0000"),
                root_mean_squared_error=Decimal("15.0000"),
                number_of_training_samples=300,
                model_version="v2024-01-01",
                is_active=True,
            )

            # Mock _load_model_artifact to return our mock model
            # and _generate_prediction_records to return partial set
            with patch(
                "predictions.tasks._load_model_artifact", return_value=mock_model
            ), patch(
                "predictions.tasks._generate_prediction_records",
                return_value=[
                    {
                        "predicted_date": today + timedelta(days=i + 1),
                        "predicted_close_price": Decimal("2100.00"),
                        "confidence_interval_lower": Decimal("2050.00"),
                        "confidence_interval_upper": Decimal("2150.00"),
                        "generation_timestamp": generation_timestamp,
                    }
                    for i in range(partial_count)
                ],
            ):
                result = generate_predictions()

            # Verify partial set was discarded
            self.assertEqual(
                result["status"],
                "partial_set_discarded",
                f"Expected partial_set_discarded with {partial_count} records, "
                f"got: {result}",
            )

            # Verify previous predictions are retained unchanged
            self.assertEqual(
                Prediction.objects.count(),
                original_count,
                "Previous predictions should be retained when partial set is discarded",
            )

            current_prices = list(
                Prediction.objects.order_by("predicted_date").values_list(
                    "predicted_close_price", flat=True
                )
            )
            self.assertEqual(
                current_prices,
                original_prices,
                "Previous prediction prices should remain unchanged",
            )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 9: Prediction API response structure
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 6.1, 6.2


class PropertyPredictionAPIResponseStructureTest(TestCase):
    """
    Property 9: Prediction API response structure

    For any GET request to /api/v1/prices/predictions when predictions exist,
    the response should be a JSON array ordered by predicted_date ascending
    where every record contains predicted_date, predicted_close_price,
    confidence_interval_lower, and confidence_interval_upper fields.
    """

    @given(
        num_predictions=st.integers(min_value=1, max_value=30),
        base_price=st.decimals(
            min_value=Decimal("500.00"),
            max_value=Decimal("5000.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
        ci_spread=st.decimals(
            min_value=Decimal("10.00"),
            max_value=Decimal("200.00"),
            places=2,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @settings(max_examples=100)
    @patch("predictions.views._get_redis_client", return_value=None)
    def test_prediction_response_structure_and_ordering(
        self, mock_redis, num_predictions, base_price, ci_spread
    ):
        """
        For any GET request to /api/v1/prices/predictions when predictions exist,
        the response should be a JSON array ordered by predicted_date ascending
        where every record contains the required fields.

        **Validates: Requirements 6.1, 6.2**
        """
        # Feature: financial-news-integration, Property 9: Prediction API response structure
        from rest_framework.test import APIClient

        client = APIClient()

        # Create predictions with varying dates
        today = date.today()
        predictions = []
        for i in range(num_predictions):
            pred_date = today + timedelta(days=i + 1)
            predictions.append(
                Prediction(
                    predicted_date=pred_date,
                    predicted_close_price=base_price + Decimal(str(i)),
                    confidence_interval_lower=base_price + Decimal(str(i)) - ci_spread,
                    confidence_interval_upper=base_price + Decimal(str(i)) + ci_spread,
                    generation_timestamp=datetime.now(timezone.utc),
                )
            )
        Prediction.objects.bulk_create(predictions)

        response = client.get("/api/v1/prices/predictions")

        self.assertEqual(response.status_code, 200)

        data = response.json()

        # Response should be a list (JSON array)
        self.assertIsInstance(
            data,
            list,
            f"Expected response to be a JSON array, got {type(data).__name__}",
        )

        # Should have the correct number of predictions
        self.assertEqual(
            len(data),
            num_predictions,
            f"Expected {num_predictions} predictions, got {len(data)}",
        )

        # Verify each record contains all required fields
        required_fields = {
            "predicted_date",
            "predicted_close_price",
            "confidence_interval_lower",
            "confidence_interval_upper",
        }
        for i, record in enumerate(data):
            for field in required_fields:
                self.assertIn(
                    field,
                    record,
                    f"Record {i} missing required field '{field}'",
                )

        # Verify ordering is ascending by predicted_date
        dates = [record["predicted_date"] for record in data]
        self.assertEqual(
            dates,
            sorted(dates),
            "Predictions should be ordered by predicted_date ascending",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Feature: financial-news-integration, Property 10: Unrecognized query parameter tolerance
# ──────────────────────────────────────────────────────────────────────────────
# Validates: Requirements 6.5


class PropertyUnrecognizedQueryParameterToleranceTest(TestCase):
    """
    Property 10: Unrecognized query parameter tolerance

    For any GET request to /api/v1/prices/predictions with arbitrary
    unrecognized query parameters, the response should be identical to the
    response without those parameters.
    """

    @given(
        num_predictions=st.integers(min_value=1, max_value=10),
        param_name=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-"),
            min_size=1,
            max_size=20,
        ),
        param_value=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_-. "),
            min_size=0,
            max_size=50,
        ),
    )
    @settings(max_examples=100)
    @patch("predictions.views._get_redis_client", return_value=None)
    def test_unrecognized_params_produce_identical_response(
        self, mock_redis, num_predictions, param_name, param_value
    ):
        """
        For any GET request to /api/v1/prices/predictions with arbitrary
        unrecognized query parameters, the response should be identical to
        the response without those parameters.

        **Validates: Requirements 6.5**
        """
        # Feature: financial-news-integration, Property 10: Unrecognized query parameter tolerance
        from rest_framework.test import APIClient

        client = APIClient()

        # Create predictions
        today = date.today()
        predictions = []
        for i in range(num_predictions):
            pred_date = today + timedelta(days=i + 1)
            predictions.append(
                Prediction(
                    predicted_date=pred_date,
                    predicted_close_price=Decimal("2000.00") + Decimal(str(i)),
                    confidence_interval_lower=Decimal("1950.00") + Decimal(str(i)),
                    confidence_interval_upper=Decimal("2050.00") + Decimal(str(i)),
                    generation_timestamp=datetime.now(timezone.utc),
                )
            )
        Prediction.objects.bulk_create(predictions)

        # Request without extra params
        response_without = client.get("/api/v1/prices/predictions")
        data_without = response_without.json()

        # Request with unrecognized params
        response_with = client.get(
            "/api/v1/prices/predictions",
            {param_name: param_value},
        )
        data_with = response_with.json()

        # Both responses should have the same status code
        self.assertEqual(
            response_without.status_code,
            response_with.status_code,
            f"Status codes differ: {response_without.status_code} vs {response_with.status_code}",
        )

        # Both responses should have identical data
        self.assertEqual(
            data_without,
            data_with,
            f"Response with unrecognized param '{param_name}={param_value}' "
            f"differs from response without params",
        )
