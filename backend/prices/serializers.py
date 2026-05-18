"""Serializers for the prices app."""

from rest_framework import serializers

from prices.models import GoldPrice


class GoldPriceSerializer(serializers.ModelSerializer):
    """Serializes GoldPrice records for API responses."""

    class Meta:
        model = GoldPrice
        fields = ["date", "open", "high", "low", "close", "volume"]
