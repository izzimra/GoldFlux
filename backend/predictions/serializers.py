"""Serializers for the predictions app."""

from rest_framework import serializers

from predictions.models import ModelMetadata, Prediction


class PredictionSerializer(serializers.ModelSerializer):
    """Serializes Prediction records for API responses."""

    class Meta:
        model = Prediction
        fields = [
            "predicted_date",
            "predicted_close_price",
            "confidence_interval_lower",
            "confidence_interval_upper",
        ]


class ModelMetadataSerializer(serializers.ModelSerializer):
    """Serializes ModelMetadata records for API responses.

    Formats training_date as ISO 8601 datetime string.
    """

    training_date = serializers.DateField(format="%Y-%m-%dT00:00:00Z")

    class Meta:
        model = ModelMetadata
        fields = [
            "training_date",
            "mean_absolute_error",
            "root_mean_squared_error",
            "number_of_training_samples",
            "model_version",
        ]
