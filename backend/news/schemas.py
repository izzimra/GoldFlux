"""
News article schema definitions.

These are plain Python dataclasses (not Django models) because news articles
are cached in Redis rather than stored in PostgreSQL.
"""

from dataclasses import dataclass


@dataclass
class NewsArticle:
    """A single financial news article with sentiment data.

    Fields are populated from the Marketaux API response and cached in Redis.
    """

    title: str  # Sanitized, HTML stripped
    source_name: str  # Sanitized source name
    source_url: str  # Original article URL
    published_at: str  # ISO 8601 timestamp
    description: str  # First 300 chars, sanitized
    sentiment_score: float  # -1.0 to 1.0
    sentiment_label: str  # "positive" | "neutral" | "negative"
