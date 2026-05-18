"""DRF serializers for news API responses."""

from rest_framework import serializers


class NewsArticleSerializer(serializers.Serializer):
    """Serializer for individual news article objects."""

    title = serializers.CharField()
    source_name = serializers.CharField()
    source_url = serializers.CharField()
    published_at = serializers.CharField()
    description = serializers.CharField()
    sentiment_score = serializers.FloatField()
    sentiment_label = serializers.CharField()


class NewsResponseSerializer(serializers.Serializer):
    """Serializer for the full news API response."""

    last_updated = serializers.CharField(allow_null=True)
    articles = NewsArticleSerializer(many=True)
    message = serializers.CharField(required=False)
