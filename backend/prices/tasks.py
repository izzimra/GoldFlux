"""Celery tasks for gold price data ingestion."""

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd
import redis
import yfinance as yf
from celery import shared_task
from django.conf import settings

from prices.models import GoldPrice

logger = logging.getLogger(__name__)

TICKER = "GC=F"
PERIOD = "5y"
FETCH_TIMEOUT = 60
CACHE_KEY_PATTERN = "cache:historical:*"


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=2,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
    retry_jitter=False,
)
def ingest_gold_prices(self):
    """
    Fetch GC=F ticker data from yfinance for the past 5 years,
    validate records, upsert to PostgreSQL, and invalidate cache.
    """
    logger.info("Starting gold price ingestion for ticker %s", TICKER)

    # Fetch data from yfinance with timeout
    try:
        ticker = yf.Ticker(TICKER)
        df = ticker.history(period=PERIOD, timeout=FETCH_TIMEOUT)
    except Exception as exc:
        logger.error(
            "Failed to fetch data from yfinance: %s (timestamp: %s)",
            exc,
            datetime.now(timezone.utc).isoformat(),
        )
        raise exc

    if df is None or df.empty:
        logger.warning("yfinance returned no data for ticker %s", TICKER)
        return {"status": "no_data", "records_processed": 0, "records_skipped": 0}

    # Reset index to get date as a column
    df = df.reset_index()

    # Validate and upsert records
    records_processed = 0
    records_skipped = 0

    for _, row in df.iterrows():
        # Validate required fields are present and not null
        try:
            date_val = row.get("Date")
            open_val = row.get("Open")
            high_val = row.get("High")
            low_val = row.get("Low")
            close_val = row.get("Close")
            volume_val = row.get("Volume")

            # Check for null/missing values
            if any(
                v is None or (hasattr(v, "__class__") and str(v) == "NaT")
                for v in [date_val]
            ):
                records_skipped += 1
                continue

            # Check numeric fields for NaN/None
            numeric_fields = [open_val, high_val, low_val, close_val, volume_val]
            if any(v is None or pd.isna(v) for v in numeric_fields):
                records_skipped += 1
                continue

            # Convert date
            if hasattr(date_val, "date"):
                record_date = date_val.date()
            else:
                record_date = date_val

            # Convert to Decimal for precision
            open_dec = Decimal(str(round(float(open_val), 2)))
            high_dec = Decimal(str(round(float(high_val), 2)))
            low_dec = Decimal(str(round(float(low_val), 2)))
            close_dec = Decimal(str(round(float(close_val), 2)))
            volume_int = int(volume_val)

        except (ValueError, TypeError, InvalidOperation) as e:
            logger.debug("Skipping record due to conversion error: %s", e)
            records_skipped += 1
            continue

        # Upsert: update on duplicate date
        GoldPrice.objects.update_or_create(
            date=record_date,
            defaults={
                "open": open_dec,
                "high": high_dec,
                "low": low_dec,
                "close": close_dec,
                "volume": volume_int,
            },
        )
        records_processed += 1

    if records_skipped > 0:
        logger.warning(
            "Skipped %d records with null/missing fields during ingestion",
            records_skipped,
        )

    # Log success
    ingestion_timestamp = datetime.now(timezone.utc).isoformat()
    logger.info(
        "Gold price ingestion completed successfully. "
        "Timestamp: %s, Records processed: %d, Records skipped: %d",
        ingestion_timestamp,
        records_processed,
        records_skipped,
    )

    # Invalidate historical price cache in Redis
    _invalidate_historical_cache()

    return {
        "status": "success",
        "timestamp": ingestion_timestamp,
        "records_processed": records_processed,
        "records_skipped": records_skipped,
    }


def _invalidate_historical_cache():
    """Invalidate all cached historical price responses in Redis."""
    try:
        redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url)
        keys = r.keys(CACHE_KEY_PATTERN)
        if keys:
            r.delete(*keys)
            logger.info(
                "Invalidated %d historical price cache entries", len(keys)
            )
        else:
            logger.debug("No historical price cache entries to invalidate")
    except redis.RedisError as e:
        logger.error("Failed to invalidate historical price cache: %s", e)
