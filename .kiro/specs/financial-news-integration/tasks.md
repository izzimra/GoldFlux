# Implementation Plan: Financial News Integration

## Overview

This plan implements the complete GoldFlux financial news integration feature, covering backend infrastructure (Django models, Celery tasks, API endpoints, middleware), the Marketaux API integration with Redis caching, and the frontend Market Insights panel with sentiment badges and responsive layout. Tasks are ordered for logical flow: infrastructure and models first, then backend services and API endpoints, then frontend components, and finally integration wiring.

## Tasks

- [x] 1. Set up database models and migrations
  - [x] 1.1 Create GoldPrice model in prices app
    - Define `GoldPrice` model in `backend/prices/models.py` with fields: date (DateField, unique, indexed), open, high, low, close (DecimalField, max_digits=10, decimal_places=2), volume (BigIntegerField), created_at, updated_at
    - Add Meta ordering by date and explicit index
    - Generate and apply migration
    - _Requirements: 1.2, 15.1, 15.2, 15.5, 15.7_

  - [x] 1.2 Create Prediction and ModelMetadata models in predictions app
    - Define `Prediction` model in `backend/predictions/models.py` with fields: predicted_date (DateField, unique, indexed), predicted_close_price, confidence_interval_lower, confidence_interval_upper (DecimalField), generation_timestamp (DateTimeField)
    - Add CheckConstraint ensuring confidence_interval_lower <= confidence_interval_upper
    - Define `ModelMetadata` model with fields: training_date, mean_absolute_error, root_mean_squared_error (DecimalField, precision 4), number_of_training_samples (IntegerField), model_version (CharField), is_active (BooleanField)
    - Generate and apply migrations
    - _Requirements: 4.2, 15.3, 15.4, 15.6, 15.7, 15.8_

  - [x] 1.3 Create news app structure and NewsArticle schema
    - Create `backend/news/` Django app with __init__.py, apps.py, urls.py, views.py, services.py, tasks.py, schemas.py, serializers.py
    - Define `NewsArticle` dataclass in `backend/news/schemas.py` with fields: title, source_name, source_url, published_at, description, sentiment_score, sentiment_label
    - Register the news app in `backend/config/settings.py` INSTALLED_APPS
    - _Requirements: 17.3, 18.2_

- [ ] 2. Implement backend middleware and security layer
  - [~] 2.1 Implement RateLimitMiddleware
    - Create `backend/config/middleware.py` with `RateLimitMiddleware` class
    - Use Redis to track request counts per IP with 60-second sliding window
    - Return HTTP 429 with Retry-After header when limit (100 requests/60s) exceeded
    - _Requirements: 12.1, 12.2, 24.1, 24.2_

  - [~] 2.2 Implement CorrelationIdMiddleware
    - Add `CorrelationIdMiddleware` in `backend/config/middleware.py`
    - Generate UUID v4 correlation_id for every request
    - Include correlation_id in all error responses (4xx and 5xx)
    - _Requirements: 13.1, 13.4_

  - [~] 2.3 Implement ErrorHandlingMiddleware
    - Add `ErrorHandlingMiddleware` in `backend/config/middleware.py`
    - Catch unhandled exceptions, return HTTP 500 with generic message (no stack traces, hostnames, or config details)
    - Log full exception details server-side
    - Handle PostgreSQL unreachable (503 after 5s timeout or 2 failed attempts)
    - Handle Redis unreachable (bypass cache silently, log error)
    - _Requirements: 13.1, 13.2, 13.3, 13.5, 13.6_

  - [~] 2.4 Configure CORS and security headers
    - Install and configure `django-cors-headers` in settings
    - Set CORS_ALLOWED_ORIGINS to configured frontend origin
    - Add security headers middleware: X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Strict-Transport-Security max-age=31536000
    - Register all middleware in correct order in settings.py
    - _Requirements: 12.3, 12.4, 12.6, 24.3, 24.4_

  - [ ]* 2.5 Write property tests for middleware
    - **Property 11: Rate limiting enforcement**
    - **Property 12: Security headers presence**
    - **Property 13: Error response safety**
    - **Validates: Requirements 12.1, 12.2, 12.6, 13.3, 13.4, 24.1, 24.2, 24.4**

- [ ] 3. Implement data ingestion pipeline
  - [~] 3.1 Implement ingest_gold_prices Celery task
    - Create `backend/prices/tasks.py` with `ingest_gold_prices` task
    - Fetch GC=F ticker data from yfinance for past 5 years with 60-second timeout
    - Validate records: skip those with null/missing fields, log count of skipped records
    - Upsert records to PostgreSQL (update on duplicate date)
    - Implement retry logic: 3 retries with exponential backoff (2s base)
    - Log ingestion timestamp and record count on success
    - Invalidate historical price cache in Redis on completion
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 8.3_

  - [~] 3.2 Configure Celery Beat schedule for daily ingestion
    - Configure `backend/config/celery.py` with Celery app and Beat schedule
    - Schedule `ingest_gold_prices` daily at configurable time (default 00:30 UTC via env var)
    - Implement duplicate task rejection (prevent concurrent ingestion runs)
    - Assign UUID v4 task identifiers
    - Ensure schedule persists across restarts
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 3.3 Write property tests for data ingestion
    - **Property 1: Price record upsert round-trip and idempotence**
    - **Property 2: Incomplete record filtering**
    - **Validates: Requirements 1.2, 1.3, 1.6**

- [ ] 4. Implement ML training and prediction pipeline
  - [~] 4.1 Implement train_model Celery task
    - Create `backend/predictions/tasks.py` with `train_model` task
    - Load Gold_Price_Records, split: most recent 63 trading days as holdout, rest as training
    - Train Prophet/Scikit-Learn time-series model
    - Save model artifact to filesystem with versioned filename (date-based)
    - Store ModelMetadata in PostgreSQL (MAE, RMSE, sample count, version, is_active flag)
    - Implement model comparison: if new MAE exceeds active MAE by >10%, retain current active model
    - Handle insufficient data (<252 days), runtime exceptions, and no-previous-model scenarios
    - Schedule after successful data ingestion
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [~] 4.2 Implement generate_predictions Celery task
    - Create `generate_predictions` task in `backend/predictions/tasks.py`
    - Generate 30 Prediction_Records for next 30 calendar days within 60s of training
    - Store predictions with predicted_close_price rounded to 2 decimal places
    - Replace all existing predictions with predicted_date > generation_timestamp
    - Discard partial sets (<30 records) and retain previous predictions
    - Handle missing model gracefully (return empty set)
    - Invalidate prediction cache in Redis on success
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 8.4_

  - [ ]* 4.3 Write property tests for ML pipeline
    - **Property 3: Training data split correctness**
    - **Validates: Requirements 3.2**

  - [ ]* 4.4 Write property tests for prediction generation
    - **Property 4: Model comparison threshold logic**
    - **Property 5: Prediction generation correctness**
    - **Property 6: Prediction replacement atomicity**
    - **Validates: Requirements 3.5, 4.1, 4.2, 4.3, 4.6, 15.7**

- [~] 5. Checkpoint - Ensure all backend pipeline tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Implement backend API endpoints for prices and predictions
  - [~] 6.1 Implement Historical Price API endpoint
    - Create `backend/prices/serializers.py` with `GoldPriceSerializer`
    - Create `HistoricalPriceView` in `backend/prices/views.py` for GET /api/v1/prices/historical
    - Support start_date and end_date query params (ISO 8601 YYYY-MM-DD), default to last 365 days
    - Validate date params: return 400 for malformed dates or start_date > end_date
    - Return JSON array ordered by date ascending, max 1095 records
    - Return empty array with 200 if no records in range
    - Implement Redis caching with 15-minute TTL
    - Register URL in `backend/prices/urls.py` and include in main urlconf
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 8.1, 8.5, 8.6, 8.7, 8.8_

  - [~] 6.2 Implement Predictions API endpoint
    - Create `backend/predictions/serializers.py` with `PredictionSerializer` and `ModelMetadataSerializer`
    - Create `PredictionListView` in `backend/predictions/views.py` for GET /api/v1/prices/predictions
    - Return JSON array ordered by predicted_date ascending with all required fields
    - Return empty array with message "Predictions are pending" if no predictions exist
    - Ignore unrecognized query parameters
    - Implement Redis caching with 60-minute TTL
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 8.2, 8.5, 8.6_

  - [~] 6.3 Implement Model Metadata API endpoint
    - Create `ModelMetadataView` in `backend/predictions/views.py` for GET /api/v1/model/metadata
    - Return latest model metadata (by training_date) with all required fields in ISO 8601 format
    - Return 404 if no model trained
    - Respond within 2 seconds
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [ ]* 6.4 Write property tests for price and prediction APIs
    - **Property 7: Historical API response correctness**
    - **Property 8: API input validation**
    - **Property 9: Prediction API response structure**
    - **Property 10: Unrecognized query parameter tolerance**
    - **Validates: Requirements 5.1, 5.2, 5.6, 5.7, 6.1, 6.2, 6.5, 12.5**

- [ ] 7. Implement Marketaux news fetching service
  - [~] 7.1 Implement MarketauxClient service
    - Create `backend/news/services.py` with `MarketauxClient` class
    - Read config from environment: NEWS_API_BASE_URL (default: https://api.marketaux.com), NEWS_API_KEY, NEWS_API_KEYWORDS (default: gold,XAU,commodities)
    - Implement `fetch_articles()` method: GET /v1/news/all with api_token, search, limit=30
    - Parse response: extract title, source, url, published_at, description (first 300 chars), sentiment_score from entities
    - Assign default sentiment_score of 0.0 when entities array is empty or score missing
    - Skip articles missing required fields (title or url), log warnings
    - Handle malformed JSON: log error with first 500 chars of response
    - Implement retry: 3 attempts with exponential backoff (5s base)
    - Validate NEWS_API_KEY at startup, log error and skip scheduling if missing
    - _Requirements: 17.2, 17.3, 17.4, 17.7, 17.8, 17.9, 19.1, 19.2, 19.3, 19.4, 23.5, 23.6_

  - [~] 7.2 Implement NewsCacheService
    - Create `NewsCacheService` class in `backend/news/services.py`
    - Implement `store_articles()`: serialize articles to JSON, SET in Redis with key `news:gold:articles` and TTL 5 hours, store `news:gold:last_updated` timestamp
    - Implement `get_cached_articles()`: GET from Redis, deserialize, return (articles, last_updated) tuple
    - Replace previous cached set entirely on store (not append)
    - _Requirements: 17.5, 17.6_

  - [~] 7.3 Implement SentimentClassifier utility
    - Create `SentimentClassifier` in `backend/news/services.py`
    - Implement `classify(score: float) -> str`: positive (>0.2), negative (<-0.2), neutral (between -0.2 and 0.2 inclusive)
    - _Requirements: 18.4_

  - [~] 7.4 Implement HTML sanitization utility
    - Create sanitization function in `backend/news/services.py`
    - Strip all HTML tags and script content from text fields (title, description, source_name)
    - Produce plain text output with no remaining markup
    - _Requirements: 24.5_

  - [ ]* 7.5 Write property tests for news services
    - **Property 14: Marketaux response parsing with defaults**
    - **Property 15: News cache replacement semantics**
    - **Property 18: Sentiment label classification**
    - **Property 19: Article filtering for missing required fields**
    - **Property 20: HTML and script sanitization**
    - **Validates: Requirements 17.3, 17.4, 17.6, 18.4, 23.6, 24.5**

- [ ] 8. Implement news Celery task and scheduling
  - [~] 8.1 Implement fetch_news Celery task
    - Create `fetch_news` task in `backend/news/tasks.py`
    - Orchestrate: call MarketauxClient.fetch_articles(), sanitize fields, classify sentiment, store via NewsCacheService
    - On success: log timestamp and article count
    - On failure (all retries exhausted): retain previous cache, log error with timestamp and HTTP status
    - On empty response: retain previous cache, log warning
    - Handle Redis unreachable on store: log error, discard fetched articles
    - Ensure independence from data ingestion and ML pipelines
    - _Requirements: 17.1, 17.5, 17.6, 17.7, 17.8, 17.9, 17.10, 23.1, 23.2, 23.4_

  - [~] 8.2 Configure Celery Beat schedule for news fetching
    - Add `fetch_news` to Celery Beat schedule: every 4 hours (configurable via NEWS_FETCH_INTERVAL_HOURS env var, range 1-12)
    - Support NEWS_API_KEYWORDS update without restart
    - Skip scheduling if NEWS_API_KEY is not configured
    - _Requirements: 17.1, 19.3, 19.5_

- [ ] 9. Implement News API endpoint
  - [~] 9.1 Implement NewsListView
    - Create `NewsListView` in `backend/news/views.py` for GET /api/v1/news/gold/
    - Serve from NewsCacheService (cache-first, no external API call on request)
    - Return flattened JSON array with all required fields: title, source_name, source_url, published_at, description, sentiment_score, sentiment_label
    - Include last_updated metadata field (ISO 8601)
    - Order articles by published_at descending
    - Support optional limit parameter (integer 1-30), default 30
    - Validate limit: return 400 if invalid
    - Return empty array with message if cache empty/expired
    - Handle Redis unreachable: return empty array with message "news is temporarily unavailable"
    - Respond within 200ms under normal load
    - Register URL in `backend/news/urls.py` and include in main urlconf
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9, 23.3_

  - [ ]* 9.2 Write property tests for News API endpoint
    - **Property 16: News API response correctness**
    - **Property 17: News limit parameter enforcement**
    - **Validates: Requirements 18.1, 18.2, 18.3, 18.9**

- [~] 10. Checkpoint - Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Implement frontend API client and utilities
  - [~] 11.1 Create centralized API client
    - Create `frontend/src/lib/api.ts` with `APIClient` class
    - Implement `fetchWithRetry<T>()` with 10-second timeout and up to 3 retries on network errors
    - Handle HTTP 429 (RateLimitError), 503 (ServiceUnavailableError), and generic errors (APIError)
    - Create typed methods: `getHistoricalPrices()`, `getPredictions()`, `getModelMetadata()`, `getNews()`
    - _Requirements: 14.1, 14.3, 14.6_

  - [~] 11.2 Create shared UI components (ErrorState, LoadingSkeleton)
    - Create `frontend/src/components/ErrorState.tsx`: reusable error display with retry button, supports different messages for timeout/503/generic errors
    - Create `frontend/src/components/LoadingSkeleton.tsx`: skeleton placeholder component
    - Style with Tailwind CSS
    - _Requirements: 14.1, 14.2, 14.3, 14.5_

- [ ] 12. Implement frontend historical and prediction charts
  - [~] 12.1 Implement HistoricalChart component
    - Create `frontend/src/components/HistoricalChart.tsx` using ApexCharts line chart
    - Display historical gold close prices, default range 1 month
    - Add date range selector: 1 month, 3 months, 6 months, 1 year, 5 years
    - Implement tooltip showing date, open, high, low, close, volume on hover
    - Show loading indicator while fetching
    - Show error state with retry on failure
    - Show "no data available" message for empty ranges
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [~] 12.2 Implement PredictionChart component
    - Create `frontend/src/components/PredictionChart.tsx`
    - Display predictions as dashed line with different color on same chart as historical data
    - Render 95% confidence interval as shaded band
    - Add vertical marker at boundary between historical and predicted data
    - Implement tooltip showing predicted_date, predicted_close_price, CI lower/upper (2 decimal places)
    - Show message when predictions unavailable
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [~] 12.3 Implement ModelInfoPanel component
    - Create `frontend/src/components/ModelInfoPanel.tsx`
    - Display training_date, MAE (2 decimal places), RMSE (2 decimal places), model_version
    - Show loading indicator while fetching
    - Show "no model trained" message when metadata unavailable (404)
    - Show error state with retry on fetch failure
    - Support manual refresh
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_

- [ ] 13. Implement frontend Market Insights panel
  - [~] 13.1 Implement SentimentBadge component
    - Create `frontend/src/components/SentimentBadge.tsx`
    - Render colored badge using Tailwind classes: bg-green-100 text-green-800 (positive), bg-gray-100 text-gray-800 (neutral), bg-red-100 text-red-800 (negative)
    - Accept sentiment_label prop
    - _Requirements: 20.3_

  - [~] 13.2 Implement NewsCard component
    - Create `frontend/src/components/NewsCard.tsx`
    - Display: title as clickable link (opens source_url in new tab), source_name, relative publication time (e.g., "2 hours ago"), SentimentBadge
    - Truncate title to 2 lines with ellipsis, show full title in tooltip on hover
    - Truncate description to 100 chars with ellipsis, expandable to full 300 chars on click
    - _Requirements: 20.2, 21.4, 21.5_

  - [~] 13.3 Implement FreshnessIndicator component
    - Create `frontend/src/components/FreshnessIndicator.tsx`
    - Display "Last updated" as relative time (e.g., "Updated 15 minutes ago")
    - Show amber warning icon when last_updated is older than 6 hours
    - Include refresh button with loading spinner while fetching
    - Disable refresh button during fetch
    - _Requirements: 22.1, 22.2, 22.3, 22.4_

  - [~] 13.4 Implement MarketInsightsPanel component
    - Create `frontend/src/components/MarketInsightsPanel.tsx`
    - Fetch news from API client on mount
    - Display FreshnessIndicator at top
    - Render NewsCard list ordered by published_at descending
    - Show max 10 articles by default with "Show More" button to load up to 30
    - Show loading skeleton while fetching
    - Show "no news available" message for empty response
    - Show error state with retry button on failure/timeout
    - _Requirements: 20.1, 20.2, 20.4, 20.5, 20.6, 20.7, 20.8_

  - [~] 13.5 Implement responsive layout for MarketInsightsPanel
    - Use Tailwind CSS responsive utilities
    - Desktop (≥1024px): render as sidebar, right of chart area, max 30% viewport width
    - Mobile (<1024px): render as full-width section below chart area
    - _Requirements: 21.1, 21.2, 21.3_

- [ ] 14. Implement frontend Dashboard page and error handling
  - [~] 14.1 Implement Dashboard page layout
    - Update `frontend/src/app/page.tsx` to orchestrate all components
    - Integrate HistoricalChart, PredictionChart, ModelInfoPanel, and MarketInsightsPanel
    - Implement data fetching on page load
    - Apply responsive layout with Tailwind CSS
    - _Requirements: 9.1, 10.1, 11.3, 20.1_

  - [~] 14.2 Implement frontend error handling states
    - Implement error state hierarchy: timeout → 503 → rate limit → error with data → error without data
    - Preserve previously loaded data on refresh failure, show error notification
    - Show full-page error state when initial load fails with no prior data
    - Allow up to 3 consecutive retries, then show persistent failure message
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

- [~] 15. Checkpoint - Ensure all frontend and backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. Integration wiring and final configuration
  - [~] 16.1 Configure Django URL routing
    - Wire all app URLs in `backend/config/urls.py`: prices, predictions, news under /api/v1/
    - Verify all endpoints are accessible: /api/v1/prices/historical, /api/v1/prices/predictions, /api/v1/model/metadata, /api/v1/news/gold/
    - _Requirements: 5.1, 6.1, 7.1, 18.1_

  - [~] 16.2 Configure environment variables and settings
    - Add all required env vars to Django settings: NEWS_API_BASE_URL, NEWS_API_KEY, NEWS_API_KEYWORDS, NEWS_FETCH_INTERVAL_HOURS, daily ingestion time
    - Configure Redis connection settings for cache and Celery broker
    - Configure PostgreSQL connection with 5-second timeout
    - Add CORS_ALLOWED_ORIGINS configuration
    - Update requirements.txt with all new dependencies
    - _Requirements: 2.1, 8.7, 13.1, 13.2, 19.1, 19.2, 19.4_

  - [~] 16.3 Wire Celery task chains
    - Configure task chain: ingest_gold_prices → train_model → generate_predictions
    - Ensure news fetch task runs independently on its own schedule
    - Verify cache invalidation triggers on pipeline completion
    - _Requirements: 3.1, 4.1, 8.3, 8.4, 23.4_

  - [ ]* 16.4 Write integration tests for full pipeline
    - Test data ingestion → training → prediction flow
    - Test news fetch → parse → cache → serve flow
    - Test cache invalidation on data refresh
    - Test Redis failover behavior (bypass cache, serve from DB)
    - Test rate limiting across all endpoints
    - _Requirements: 8.3, 8.4, 8.7, 8.8, 12.1, 16.1, 16.4_

- [~] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python 3.11+ with Django REST Framework; the frontend uses TypeScript with Next.js
- Redis serves dual duty as Celery broker and caching layer
- The news pipeline operates independently from the price/ML pipeline to prevent cascading failures

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 2, "tasks": ["2.5", "3.1", "7.1", "7.2", "7.3", "7.4"] },
    { "id": 3, "tasks": ["3.2", "3.3", "4.1", "7.5", "8.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "8.2"] },
    { "id": 5, "tasks": ["4.4", "6.1", "6.2", "6.3", "9.1"] },
    { "id": 6, "tasks": ["6.4", "9.2", "11.1", "11.2"] },
    { "id": 7, "tasks": ["12.1", "12.2", "12.3", "13.1"] },
    { "id": 8, "tasks": ["13.2", "13.3"] },
    { "id": 9, "tasks": ["13.4", "13.5"] },
    { "id": 10, "tasks": ["14.1", "14.2"] },
    { "id": 11, "tasks": ["16.1", "16.2", "16.3"] },
    { "id": 12, "tasks": ["16.4"] }
  ]
}
```
