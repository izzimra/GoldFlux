"""Celery tasks for ML model training and prediction generation."""

import logging
import traceback
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import joblib
import numpy as np
import redis
from celery import shared_task
from django.conf import settings
from django.db import transaction
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler

from predictions.models import ModelMetadata, Prediction
from prices.models import GoldPrice

logger = logging.getLogger(__name__)

# Training constants
MIN_TRAINING_DAYS = 252
HOLDOUT_DAYS = 63
MAE_DEGRADATION_THRESHOLD = 0.10  # 10%


@shared_task(
    bind=True,
    autoretry_for=(),
    retry_kwargs={"max_retries": 0},
)
def train_model(self):
    """
    Train a time-series model on Gold_Price_Records.

    - Loads all price records ordered by date
    - Splits: most recent 63 trading days as holdout, rest as training
    - Trains a Ridge regression with polynomial features
    - Saves model artifact to filesystem with versioned filename
    - Stores ModelMetadata in PostgreSQL
    - Implements model comparison: if new MAE exceeds active MAE by >10%,
      retains current active model
    """
    logger.info("Starting ML model training")

    try:
        # Load all gold price records ordered by date
        records = GoldPrice.objects.order_by("date").values_list(
            "date", "close"
        )
        records_list = list(records)
        total_records = len(records_list)

        # Check for insufficient data
        if total_records < MIN_TRAINING_DAYS:
            msg = (
                f"Insufficient data for training: {total_records} records "
                f"available, minimum {MIN_TRAINING_DAYS} required"
            )
            logger.error(msg)
            _handle_no_previous_model_scenario(msg)
            return {
                "status": "insufficient_data",
                "records_available": total_records,
                "minimum_required": MIN_TRAINING_DAYS,
            }

        # Split data: most recent 63 trading days as holdout, rest as training
        holdout_start_idx = total_records - HOLDOUT_DAYS
        train_data = records_list[:holdout_start_idx]
        holdout_data = records_list[holdout_start_idx:]

        # Prepare features: use ordinal day number as feature
        train_dates, train_prices = zip(*train_data)
        holdout_dates, holdout_prices = zip(*holdout_data)

        # Convert dates to ordinal numbers for regression
        X_train = np.array([d.toordinal() for d in train_dates]).reshape(-1, 1)
        y_train = np.array([float(p) for p in train_prices])

        X_holdout = np.array([d.toordinal() for d in holdout_dates]).reshape(-1, 1)
        y_holdout = np.array([float(p) for p in holdout_prices])

        # Build and train the model pipeline
        model = Pipeline([
            ("scaler", StandardScaler()),
            ("poly", PolynomialFeatures(degree=3, include_bias=False)),
            ("ridge", Ridge(alpha=1.0)),
        ])

        model.fit(X_train, y_train)

        # Evaluate on holdout set
        y_pred = model.predict(X_holdout)
        mae = mean_absolute_error(y_holdout, y_pred)
        rmse = float(np.sqrt(mean_squared_error(y_holdout, y_pred)))

        # Generate version string
        today = date.today()
        model_version = f"v{today.isoformat()}"

        logger.info(
            "Model training completed. MAE: %.4f, RMSE: %.4f, "
            "Training samples: %d, Version: %s",
            mae,
            rmse,
            len(train_data),
            model_version,
        )

        # Model comparison: check against current active model
        should_activate = _should_activate_new_model(mae)

        # Save model artifact to filesystem
        _save_model_artifact(model, model_version)

        # Store ModelMetadata in PostgreSQL
        if should_activate:
            # Deactivate all existing active models
            ModelMetadata.objects.filter(is_active=True).update(is_active=False)

        metadata = ModelMetadata.objects.create(
            training_date=today,
            mean_absolute_error=Decimal(str(round(mae, 4))),
            root_mean_squared_error=Decimal(str(round(rmse, 4))),
            number_of_training_samples=len(train_data),
            model_version=model_version,
            is_active=should_activate,
        )

        logger.info(
            "Model metadata stored. ID: %d, Active: %s, Version: %s",
            metadata.id,
            should_activate,
            model_version,
        )

        return {
            "status": "success",
            "model_version": model_version,
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "training_samples": len(train_data),
            "is_active": should_activate,
        }

    except Exception as exc:
        # Log full stack trace and retain previous model
        logger.error(
            "Model training failed with runtime exception:\n%s",
            traceback.format_exc(),
        )
        _handle_no_previous_model_scenario(str(exc))
        return {
            "status": "error",
            "error": str(exc),
        }


def _should_activate_new_model(new_mae: float) -> bool:
    """
    Determine if the new model should become the active model.

    If no active model exists, the new model is activated.
    If the new MAE exceeds the active MAE by more than 10%, retain current.
    """
    try:
        active_model = ModelMetadata.objects.filter(is_active=True).first()
    except Exception:
        # If we can't query, default to activating
        return True

    if active_model is None:
        # No previous model — activate the new one
        logger.info("No active model found. New model will be activated.")
        return True

    active_mae = float(active_model.mean_absolute_error)

    if active_mae == 0:
        # Edge case: avoid division issues, activate new model
        return True

    # Check if new MAE exceeds active MAE by more than 10%
    threshold = active_mae * (1 + MAE_DEGRADATION_THRESHOLD)

    if new_mae > threshold:
        logger.warning(
            "New model MAE (%.4f) exceeds active model MAE (%.4f) by more "
            "than 10%% (threshold: %.4f). Retaining current active model.",
            new_mae,
            active_mae,
            threshold,
        )
        return False

    return True


def _save_model_artifact(model, model_version: str) -> None:
    """Save the trained model artifact to the filesystem."""
    models_dir = settings.ML_MODELS_DIR
    models_dir.mkdir(parents=True, exist_ok=True)

    filename = f"model_{model_version}.pkl"
    filepath = models_dir / filename

    joblib.dump(model, filepath)
    logger.info("Model artifact saved to %s", filepath)


def _handle_no_previous_model_scenario(error_msg: str) -> None:
    """
    Handle the case where training fails and no previous model exists.
    Logs appropriate message based on whether an active model is available.
    """
    active_model = ModelMetadata.objects.filter(is_active=True).first()

    if active_model is None:
        logger.error(
            "No model is available. Training failed and no previous model "
            "exists. System status: awaiting_initial_model. Error: %s",
            error_msg,
        )
    else:
        logger.info(
            "Retaining previous active model (version: %s) after training "
            "failure. Error: %s",
            active_model.model_version,
            error_msg,
        )

# ──────────────────────────────────────────────────────────────────────────────
# Prediction Generation
# ──────────────────────────────────────────────────────────────────────────────

PREDICTION_DAYS = 30
PREDICTION_CACHE_KEY_PATTERN = "cache:predictions:*"
CONFIDENCE_PERCENTAGE = 0.05  # 5% of predicted price for CI band


@shared_task(
    bind=True,
    autoretry_for=(),
    retry_kwargs={"max_retries": 0},
)
def generate_predictions(self):
    """
    Generate 30 Prediction_Records for the next 30 calendar days.

    - Loads the active model artifact from the filesystem
    - Generates predictions for the next 30 calendar days
    - Stores predictions with predicted_close_price rounded to 2 decimal places
    - Replaces all existing predictions with predicted_date > generation_timestamp
    - Discards partial sets (<30 records) and retains previous predictions
    - Handles missing model gracefully (returns empty set)
    - Invalidates prediction cache in Redis on success
    """
    logger.info("Starting prediction generation")

    generation_timestamp = datetime.now(timezone.utc)

    # Load the active model
    active_model_metadata = ModelMetadata.objects.filter(is_active=True).first()

    if active_model_metadata is None:
        logger.warning(
            "No active model found. Cannot generate predictions. "
            "Returning empty prediction set."
        )
        return {
            "status": "no_model",
            "predictions_generated": 0,
        }

    # Load model artifact from filesystem
    model = _load_model_artifact(active_model_metadata.model_version)

    if model is None:
        logger.warning(
            "Could not load model artifact for version %s. "
            "Returning empty prediction set.",
            active_model_metadata.model_version,
        )
        return {
            "status": "model_load_failed",
            "predictions_generated": 0,
        }

    try:
        # Generate predictions for the next 30 calendar days
        predictions = _generate_prediction_records(
            model, generation_timestamp
        )

        # Validate we have exactly 30 predictions
        if len(predictions) < PREDICTION_DAYS:
            logger.warning(
                "Prediction generation produced %d records (expected %d). "
                "Discarding partial set and retaining previous predictions.",
                len(predictions),
                PREDICTION_DAYS,
            )
            return {
                "status": "partial_set_discarded",
                "predictions_generated": len(predictions),
                "expected": PREDICTION_DAYS,
            }

        # Replace existing predictions atomically
        _replace_predictions(predictions, generation_timestamp)

        # Invalidate prediction cache in Redis
        _invalidate_prediction_cache()

        logger.info(
            "Prediction generation completed successfully. "
            "Generated %d predictions. Generation timestamp: %s",
            len(predictions),
            generation_timestamp.isoformat(),
        )

        return {
            "status": "success",
            "predictions_generated": len(predictions),
            "generation_timestamp": generation_timestamp.isoformat(),
            "model_version": active_model_metadata.model_version,
        }

    except Exception as exc:
        logger.error(
            "Prediction generation failed with exception:\n%s",
            traceback.format_exc(),
        )
        return {
            "status": "error",
            "error": str(exc),
            "predictions_generated": 0,
        }


def _load_model_artifact(model_version: str):
    """
    Load a trained model artifact from the filesystem.

    Returns the model object or None if loading fails.
    """
    models_dir = settings.ML_MODELS_DIR
    filename = f"model_{model_version}.pkl"
    filepath = models_dir / filename

    try:
        model = joblib.load(filepath)
        logger.info("Loaded model artifact from %s", filepath)
        return model
    except FileNotFoundError:
        logger.error("Model artifact not found at %s", filepath)
        return None
    except Exception as exc:
        logger.error(
            "Failed to load model artifact from %s: %s", filepath, exc
        )
        return None


def _generate_prediction_records(model, generation_timestamp):
    """
    Generate prediction records for the next 30 calendar days.

    Uses the loaded model to predict prices and numpy to compute
    confidence intervals based on a percentage of the predicted price.
    """
    predictions = []
    today = generation_timestamp.date()

    # Generate future dates (next 30 calendar days)
    future_dates = [today + timedelta(days=i + 1) for i in range(PREDICTION_DAYS)]

    # Convert dates to ordinal numbers for the model
    X_future = np.array([d.toordinal() for d in future_dates]).reshape(-1, 1)

    # Generate predictions using the model
    predicted_prices = model.predict(X_future)

    for i, pred_date in enumerate(future_dates):
        predicted_price = round(float(predicted_prices[i]), 2)

        # Compute confidence intervals based on a percentage of predicted price
        ci_margin = abs(predicted_price) * CONFIDENCE_PERCENTAGE
        ci_lower = round(predicted_price - ci_margin, 2)
        ci_upper = round(predicted_price + ci_margin, 2)

        predictions.append({
            "predicted_date": pred_date,
            "predicted_close_price": Decimal(str(predicted_price)),
            "confidence_interval_lower": Decimal(str(ci_lower)),
            "confidence_interval_upper": Decimal(str(ci_upper)),
            "generation_timestamp": generation_timestamp,
        })

    return predictions


@transaction.atomic
def _replace_predictions(predictions, generation_timestamp):
    """
    Replace all existing predictions with predicted_date > generation_timestamp.

    This operation is atomic — either all predictions are replaced or none are.
    """
    # Delete existing predictions with predicted_date > generation date
    Prediction.objects.filter(
        predicted_date__gt=generation_timestamp.date()
    ).delete()

    # Bulk create new predictions
    prediction_objects = [
        Prediction(
            predicted_date=p["predicted_date"],
            predicted_close_price=p["predicted_close_price"],
            confidence_interval_lower=p["confidence_interval_lower"],
            confidence_interval_upper=p["confidence_interval_upper"],
            generation_timestamp=p["generation_timestamp"],
        )
        for p in predictions
    ]

    Prediction.objects.bulk_create(prediction_objects)
    logger.info(
        "Replaced predictions: deleted existing future predictions and "
        "created %d new prediction records.",
        len(prediction_objects),
    )


def _invalidate_prediction_cache():
    """Invalidate all cached prediction responses in Redis."""
    try:
        redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        keys = r.keys(PREDICTION_CACHE_KEY_PATTERN)
        if keys:
            r.delete(*keys)
            logger.info(
                "Invalidated %d prediction cache entries", len(keys)
            )
        else:
            logger.debug("No prediction cache entries to invalidate")
    except redis.RedisError as e:
        logger.error("Failed to invalidate prediction cache: %s", e)
