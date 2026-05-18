# Requirements Document

## Introduction

GoldFlux is a production-grade Gold Price Prediction and Market Intelligence web application. It aggregates historical gold market data, trains machine learning models to forecast future prices, integrates real-time financial news with sentiment analysis, and presents all insights on an interactive dashboard. The system uses a React/Next.js frontend with Tailwind CSS and ApexCharts for visualization, a Django REST Framework backend, PostgreSQL for persistent storage, Redis for caching and task queuing, and Celery for asynchronous ML training, data ingestion, and news fetching pipelines. Market price data is sourced from the yfinance library using the GC=F (Gold Futures) ticker. Financial news and sentiment data is sourced from the Marketaux API (/v1/news/all endpoint) filtered for gold, XAU, and commodities keywords.

## Glossary

- **Dashboard**: The primary frontend interface displaying historical gold prices, predicted prices, model performance metrics, and the Market Insights news panel
- **Data_Ingestion_Pipeline**: The automated Celery-based process that fetches gold price data from yfinance and stores it in PostgreSQL
- **ML_Training_Pipeline**: The automated Celery-based process that trains or retrains the prediction model on historical data
- **Prediction_Engine**: The component that generates gold price forecasts using the trained ML model
- **API_Gateway**: The Django REST Framework layer that serves historical data, predictions, model metadata, and news to the frontend
- **Cache_Layer**: The Redis-based caching system that stores frequently accessed API responses, intermediate computation results, and cached news articles
- **Task_Queue**: The Celery/Redis-based system that manages asynchronous background jobs for data ingestion, model training, and news fetching
- **Gold_Price_Record**: A single data point containing date, open, high, low, close, and volume for the GC=F ticker
- **Prediction_Record**: A forecasted price data point containing a future date and predicted close price with confidence interval
- **Model_Metadata**: Information about the trained model including training date, accuracy metrics, and hyperparameters
- **News_Fetcher**: The scheduled Celery task that executes a GET request to the Marketaux API every 4 hours and caches parsed articles in Redis
- **Marketaux_API**: The external financial news API service (https://api.marketaux.com/v1/news/all) used as the data source for gold and commodity news
- **News_Article**: A single news item containing a title, source name, source URL, publication timestamp, description text, and sentiment score
- **Sentiment_Score**: A numeric value provided by Marketaux representing the sentiment of a News_Article, mapped to a Sentiment_Label on the backend
- **Sentiment_Label**: A categorical classification derived from the Sentiment_Score: "positive" (score > 0.2), "neutral" (score between -0.2 and 0.2 inclusive), or "negative" (score < -0.2)
- **News_Cache**: The Redis-based store holding the most recently fetched and parsed array of News_Articles with a defined time-to-live
- **News_API_Endpoint**: The Django REST Framework endpoint (GET /api/v1/news/gold/) that serves cached news data to the frontend as a clean flattened JSON array
- **Market_Insights_Panel**: The frontend React component (styled with Tailwind CSS) that displays News_Articles on the Dashboard with titles, metadata, and dynamic sentiment badges
- **User**: A person accessing the GoldFlux dashboard to view gold price data, predictions, and market news

## Requirements

### Requirement 1: Historical Data Ingestion

**User Story:** As a system operator, I want the application to automatically fetch and store historical gold price data, so that the ML model has sufficient training data and the dashboard can display historical trends.

#### Acceptance Criteria

1. WHEN the Data_Ingestion_Pipeline is triggered, THE Data_Ingestion_Pipeline SHALL fetch daily gold price data for the GC=F ticker from yfinance covering at minimum the past 5 years of trading days, with a fetch operation timeout of 60 seconds
2. WHEN new price data is fetched, THE Data_Ingestion_Pipeline SHALL store each Gold_Price_Record in PostgreSQL with fields: date, open, high, low, close (each stored to 2 decimal places), and volume
3. WHEN the Data_Ingestion_Pipeline encounters duplicate date entries, THE Data_Ingestion_Pipeline SHALL update the existing record rather than creating a duplicate
4. IF the yfinance API is unreachable or returns an error, THEN THE Data_Ingestion_Pipeline SHALL log the error with a timestamp and retry up to 3 times with exponential backoff starting at a 2-second base delay
5. IF all 3 retry attempts are exhausted without a successful response, THEN THE Data_Ingestion_Pipeline SHALL log a final failure message with the error details and terminate the ingestion run without modifying existing stored data
6. IF the yfinance API returns records with null or missing values in any of the required fields (date, open, high, low, close, volume), THEN THE Data_Ingestion_Pipeline SHALL skip those incomplete records and log the count of skipped records
7. WHEN the Data_Ingestion_Pipeline completes successfully, THE Data_Ingestion_Pipeline SHALL record the ingestion timestamp and number of records processed in the system log

### Requirement 2: Scheduled Data Refresh

**User Story:** As a system operator, I want data ingestion to run on a daily schedule, so that the application always has up-to-date market data without manual intervention.

#### Acceptance Criteria

1. THE Task_Queue SHALL schedule the Data_Ingestion_Pipeline to execute once daily at a configurable time (default: 00:30 UTC), where the schedule time is specified as an HH:MM value in UTC via environment variable or application configuration
2. WHEN a scheduled ingestion task is queued, THE Task_Queue SHALL assign it a unique task identifier (UUID v4 format) for tracking
3. IF a scheduled ingestion task fails after 3 retry attempts, THEN THE Task_Queue SHALL mark the task as failed and emit an alert-level log entry containing the task identifier, failure timestamp, and error reason
4. WHILE a Data_Ingestion_Pipeline task is already running, THE Task_Queue SHALL reject duplicate ingestion requests and log the rejection including the rejected task identifier and the identifier of the currently running task
5. IF a scheduled ingestion task fails, THEN THE Task_Queue SHALL continue executing subsequent daily scheduled runs at the configured time without manual intervention
6. THE Task_Queue SHALL persist the daily schedule configuration such that the schedule resumes automatically after a system restart without requiring manual re-registration

### Requirement 3: ML Model Training

**User Story:** As a data scientist, I want the system to automatically train a prediction model on historical data, so that forecasts remain accurate as new market data becomes available.

#### Acceptance Criteria

1. WHEN the Data_Ingestion_Pipeline completes successfully, THE Task_Queue SHALL schedule the ML_Training_Pipeline to execute once daily
2. WHEN the ML_Training_Pipeline executes, THE ML_Training_Pipeline SHALL train a time-series forecasting model (Prophet or Scikit-Learn regression) using Gold_Price_Records, reserving the most recent 63 trading days as a holdout test set and using all prior records as the training set
3. WHEN training completes, THE ML_Training_Pipeline SHALL persist the trained model artifact to the filesystem with a versioned filename including the training date
4. WHEN training completes, THE ML_Training_Pipeline SHALL store Model_Metadata in PostgreSQL including: training_date, mean_absolute_error, root_mean_squared_error, number_of_training_samples, model_version, and a flag indicating whether the model is the active model
5. IF the newly trained model's mean_absolute_error on the holdout set exceeds the current active model's mean_absolute_error by more than 10%, THEN THE ML_Training_Pipeline SHALL log a warning, retain the current active model, and store the new model's metadata with the active flag set to false
6. IF model training fails due to insufficient data (fewer than 252 trading days), THEN THE ML_Training_Pipeline SHALL log an error and retain the previous model version as active
7. IF model training fails due to a runtime exception, THEN THE ML_Training_Pipeline SHALL log the full stack trace and retain the previous model version as active
8. IF model training fails and no previous model version exists, THEN THE ML_Training_Pipeline SHALL log an error indicating no model is available and set the system training status to "awaiting_initial_model"

### Requirement 4: Price Prediction Generation

**User Story:** As a user, I want the system to generate gold price predictions, so that I can view forecasted prices on the dashboard.

#### Acceptance Criteria

1. WHEN the ML_Training_Pipeline completes successfully, THE Prediction_Engine SHALL generate Prediction_Records for the next 30 calendar days within 60 seconds of training completion
2. THE Prediction_Engine SHALL store each Prediction_Record in PostgreSQL with fields: predicted_date, predicted_close_price (rounded to 2 decimal places), confidence_interval_lower, confidence_interval_upper, and generation_timestamp
3. WHEN new predictions are generated, THE Prediction_Engine SHALL replace all existing Prediction_Records with a predicted_date later than the generation timestamp
4. THE Prediction_Engine SHALL use the most recently trained model version for all predictions
5. IF the Prediction_Engine cannot load a trained model, THEN THE Prediction_Engine SHALL return an empty prediction set containing zero Prediction_Records and store no new records in PostgreSQL
6. IF the Prediction_Engine generates fewer than 30 Prediction_Records due to a processing error, THEN THE Prediction_Engine SHALL discard the partial set, retain the previous Prediction_Records, and log a warning
7. WHEN new predictions are successfully stored, THE Prediction_Engine SHALL record the generation_timestamp so that the dashboard can display when predictions were last updated

### Requirement 5: Historical Data API

**User Story:** As a frontend developer, I want a REST API endpoint that returns historical gold price data, so that the dashboard can render historical price charts.

#### Acceptance Criteria

1. WHEN a GET request is received at /api/v1/prices/historical, THE API_Gateway SHALL return a JSON array of Gold_Price_Records ordered by date ascending, containing no more than 1095 records per response
2. WHEN the request includes query parameters start_date and end_date in ISO 8601 date format (YYYY-MM-DD), THE API_Gateway SHALL filter results to only include records within that date range (inclusive)
3. WHEN no date parameters are provided, THE API_Gateway SHALL return the most recent 365 days of Gold_Price_Records
4. THE API_Gateway SHALL respond to historical data requests within 500 milliseconds under normal load (fewer than 100 concurrent requests)
5. IF no records exist for the requested date range, THEN THE API_Gateway SHALL return an empty JSON array with HTTP status 200
6. IF the request includes a start_date that is after the end_date, THEN THE API_Gateway SHALL return HTTP status 400 with an error message indicating that start_date must be on or before end_date
7. IF the request includes date parameters that are missing, malformed, or not in ISO 8601 format (YYYY-MM-DD), THEN THE API_Gateway SHALL return HTTP status 400 with an error message indicating the expected date format

### Requirement 6: Predictions API

**User Story:** As a frontend developer, I want a REST API endpoint that returns predicted gold prices, so that the dashboard can display forecasted trends.

#### Acceptance Criteria

1. WHEN a GET request is received at /api/v1/prices/predictions, THE API_Gateway SHALL return a JSON array of Prediction_Records ordered by predicted_date ascending, where each Prediction_Record includes at minimum: predicted_date, predicted_close_price, confidence_interval_lower, and confidence_interval_upper
2. THE API_Gateway SHALL include confidence_interval_lower and confidence_interval_upper representing a 95% confidence level in each Prediction_Record response
3. WHILE the system is under normal load of fewer than 100 concurrent requests, THE API_Gateway SHALL respond to prediction requests within 300 milliseconds measured from request receipt to first response byte
4. IF no predictions are available, THEN THE API_Gateway SHALL return an empty JSON array with HTTP status 200 and a message field indicating predictions are pending
5. IF the GET request to /api/v1/prices/predictions includes unrecognized query parameters, THEN THE API_Gateway SHALL ignore the unrecognized parameters and return the default prediction response

### Requirement 7: Model Metadata API

**User Story:** As a user, I want to see information about the prediction model, so that I can assess the reliability of the forecasts.

#### Acceptance Criteria

1. WHEN a GET request is received at /api/v1/model/metadata, THE API_Gateway SHALL return HTTP status 200 with a JSON response containing the Model_Metadata for the most recently trained model, determined by the latest training_date
2. THE API_Gateway SHALL include training_date (ISO 8601 format), mean_absolute_error (numeric), root_mean_squared_error (numeric), number_of_training_samples (integer), and model_version (string) in the response
3. IF no model has been trained, THEN THE API_Gateway SHALL return HTTP status 404 with an error message indicating that no trained model is available
4. WHEN a GET request is received at /api/v1/model/metadata, THE API_Gateway SHALL return the response within 2 seconds

### Requirement 8: API Response Caching

**User Story:** As a system operator, I want API responses to be cached, so that repeated requests are served quickly and database load is reduced.

#### Acceptance Criteria

1. WHEN the API_Gateway serves a response for /api/v1/prices/historical, THE Cache_Layer SHALL cache the response in Redis with a time-to-live of 15 minutes, using a cache key derived from the full request path including all query parameters
2. WHEN the API_Gateway serves a response for /api/v1/prices/predictions, THE Cache_Layer SHALL cache the response in Redis with a time-to-live of 60 minutes, using a cache key derived from the full request path including all query parameters
3. WHEN the Data_Ingestion_Pipeline completes successfully, THE Cache_Layer SHALL invalidate all cached historical price responses
4. WHEN the Prediction_Engine generates new predictions, THE Cache_Layer SHALL invalidate all cached prediction responses
5. WHILE a cache entry exists that has not exceeded its time-to-live and has not been invalidated, THE API_Gateway SHALL serve the cached response without querying PostgreSQL
6. IF a cache entry does not exist or has expired for an incoming request, THEN THE API_Gateway SHALL query PostgreSQL, serve the response, and store the result in the Cache_Layer before returning
7. IF Redis is unavailable, THEN THE API_Gateway SHALL bypass the Cache_Layer and serve responses directly from PostgreSQL within 5 seconds
8. IF Redis is unavailable, THEN THE Cache_Layer SHALL log an error indicating cache unavailability and THE API_Gateway SHALL continue processing requests without interruption

### Requirement 9: Frontend Dashboard - Historical Chart

**User Story:** As a user, I want to view historical gold prices on an interactive chart, so that I can analyze past market trends.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Dashboard SHALL display an ApexCharts line chart showing historical gold close prices for the default date range of 1 month
2. THE Dashboard SHALL allow the User to select predefined date ranges: 1 month, 3 months, 6 months, 1 year, and 5 years
3. WHEN the User hovers over a data point on the chart, THE Dashboard SHALL display a tooltip showing the date, open, high, low, close, and volume values
4. WHEN the User selects a different date range, THE Dashboard SHALL fetch and render the corresponding data within 2 seconds
5. WHILE the Dashboard is fetching data from the API_Gateway, THE Dashboard SHALL display a loading indicator
6. IF the API_Gateway request fails or times out, THEN THE Dashboard SHALL display an error message indicating the data could not be loaded and provide a retry option
7. IF the selected date range returns no data points, THEN THE Dashboard SHALL display a message indicating no data is available for the selected range

### Requirement 10: Frontend Dashboard - Prediction Chart

**User Story:** As a user, I want to view predicted gold prices alongside historical data, so that I can see the forecasted trend in context.

#### Acceptance Criteria

1. THE Dashboard SHALL display predicted gold prices as a distinct visual series (dashed line with a different color) on the same chart as historical data, showing up to 30 days of predicted values on a shared time axis
2. THE Dashboard SHALL render the 95% confidence interval as a shaded band around the prediction line
3. WHEN the User hovers over a prediction data point, THE Dashboard SHALL display a tooltip showing the predicted_date, predicted_close_price (to 2 decimal places), confidence_interval_lower (to 2 decimal places), and confidence_interval_upper (to 2 decimal places)
4. THE Dashboard SHALL visually distinguish the boundary between historical data and predictions with a vertical marker
5. IF prediction data is unavailable or empty, THEN THE Dashboard SHALL display the historical chart without the prediction series and show a message indicating that predictions are not yet available

### Requirement 11: Frontend Dashboard - Model Information Panel

**User Story:** As a user, I want to see model performance metrics on the dashboard, so that I can understand the reliability of predictions.

#### Acceptance Criteria

1. THE Dashboard SHALL display a panel showing the current model's training_date, mean_absolute_error (rounded to 2 decimal places), root_mean_squared_error (rounded to 2 decimal places), and model_version
2. IF the model metadata is unavailable because no model has been trained, THEN THE Dashboard SHALL display a message indicating that no model has been trained yet
3. WHEN the page loads, THE Dashboard SHALL fetch and display the latest model metadata
4. WHEN the User manually triggers a refresh, THE Dashboard SHALL fetch and display the latest model metadata
5. WHILE the Dashboard is fetching model metadata, THE Dashboard SHALL display a loading indicator in the model information panel
6. IF the model metadata fetch fails due to a network or server error, THEN THE Dashboard SHALL display an error message indicating that model information could not be loaded and SHALL provide the option to retry

### Requirement 12: API Security

**User Story:** As a system operator, I want the API to be secured against common threats, so that the application is protected from unauthorized access and abuse.

#### Acceptance Criteria

1. THE API_Gateway SHALL enforce rate limiting of 100 requests per fixed 60-second window per IP address across all endpoints including /api/v1/news/gold/
2. IF a client exceeds the rate limit, THEN THE API_Gateway SHALL return HTTP status 429 with a Retry-After header indicating the number of seconds remaining until the current rate limit window resets
3. THE API_Gateway SHALL set CORS headers to allow requests only from the configured frontend origin domain
4. IF a request originates from a non-allowed origin, THEN THE API_Gateway SHALL omit the Access-Control-Allow-Origin header from the response
5. IF a request contains a query parameter that fails type, format, or length validation, THEN THE API_Gateway SHALL reject the request with HTTP status 400 and an error message indicating which parameter failed validation and the reason for rejection
6. THE API_Gateway SHALL include the following security headers in all responses: X-Content-Type-Options set to nosniff, X-Frame-Options set to DENY, and Strict-Transport-Security with a max-age of at least 31536000 seconds

### Requirement 13: Error Handling and Resilience

**User Story:** As a system operator, I want the application to handle errors gracefully, so that partial failures do not bring down the entire system.

#### Acceptance Criteria

1. IF the PostgreSQL database is unreachable after a connection timeout of 5 seconds or 2 consecutive failed connection attempts, THEN THE API_Gateway SHALL return HTTP status 503 with a message indicating temporary unavailability and SHALL include a correlation_id in the response
2. IF the Redis Cache_Layer is unreachable after a connection timeout of 2 seconds, THEN THE API_Gateway SHALL bypass caching and serve responses directly from PostgreSQL with no user-visible error
3. WHEN an unhandled exception occurs in any API endpoint, THE API_Gateway SHALL return HTTP status 500 with a generic error message that does not expose internal system details (stack traces, hostnames, or configuration) and SHALL log the full exception details server-side
4. THE API_Gateway SHALL include a correlation_id in UUID v4 format in all error responses to facilitate debugging
5. IF the Task_Queue (Celery/Redis) is unreachable after a connection timeout of 5 seconds, THEN THE Data_Ingestion_Pipeline SHALL log the failure including a timestamp and the affected component name, and THE API_Gateway SHALL continue serving existing data from PostgreSQL
6. IF any downstream dependency (PostgreSQL, Redis, or Task_Queue) remains unreachable for more than 30 seconds, THEN THE API_Gateway SHALL log a persistent connectivity failure event at ERROR level

### Requirement 14: Frontend Error States

**User Story:** As a user, I want to see meaningful error messages when something goes wrong, so that I understand the current system state.

#### Acceptance Criteria

1. IF the Dashboard fails to fetch data from the API_Gateway, THEN THE Dashboard SHALL display a non-technical error message indicating the data could not be loaded, along with a retry button that re-initiates the failed request when activated
2. IF the API_Gateway returns HTTP status 503, THEN THE Dashboard SHALL display a message indicating the service is temporarily unavailable
3. WHEN the Dashboard encounters a network timeout (exceeding 10 seconds), THE Dashboard SHALL display a timeout message and offer a retry option that re-initiates the failed request when activated
4. IF a data refresh attempt fails while previously loaded data is present on screen, THEN THE Dashboard SHALL preserve the previously loaded data and display an error notification that remains visible until the user dismisses it or a subsequent refresh succeeds
5. IF the initial data load fails and no previously loaded data is available, THEN THE Dashboard SHALL display a full-page error state with a retry button and no stale content
6. IF a retry attempt fails, THEN THE Dashboard SHALL allow the user to retry again up to 3 consecutive attempts, after which THE Dashboard SHALL display a message indicating persistent failure and suggest trying again later

### Requirement 15: Database Schema and Data Integrity

**User Story:** As a system operator, I want the database schema to enforce data integrity, so that the application operates on consistent and valid data.

#### Acceptance Criteria

1. THE PostgreSQL database SHALL enforce a unique constraint on the date field of the Gold_Price_Record table
2. THE PostgreSQL database SHALL enforce NOT NULL constraints on date, open, high, low, close, and volume fields of the Gold_Price_Record table
3. THE PostgreSQL database SHALL enforce a unique constraint on the predicted_date field of the Prediction_Record table
4. THE PostgreSQL database SHALL enforce NOT NULL constraints on predicted_date, predicted_close_price, confidence_interval_lower, and confidence_interval_upper fields of the Prediction_Record table
5. THE PostgreSQL database SHALL index the date field of the Gold_Price_Record table to support range queries returning results within 100 milliseconds for datasets up to 50 years of daily records
6. IF a record is inserted or updated with a date or predicted_date that violates a unique constraint, THEN THE PostgreSQL database SHALL reject the operation and return an error indicating a duplicate entry exists for that date
7. THE PostgreSQL database SHALL store open, high, low, close, and predicted_close_price fields as numeric values with precision of at least 2 decimal places, and SHALL enforce that confidence_interval_lower is less than or equal to confidence_interval_upper
8. THE PostgreSQL database SHALL index the predicted_date field of the Prediction_Record table for range queries

### Requirement 16: Scalability and Performance

**User Story:** As a system operator, I want the application to handle growth in data volume and user traffic, so that performance remains acceptable over time.

#### Acceptance Criteria

1. THE API_Gateway SHALL support at least 100 concurrent client connections without any individual response exceeding the specified response time thresholds defined in the API response time requirements
2. THE Data_Ingestion_Pipeline SHALL fetch, validate, and store up to 10 years of daily Gold_Price_Records (approximately 2,520 records) within 60 seconds measured from initiation to completion of persistence
3. THE ML_Training_Pipeline SHALL complete model training on 10 years of data within 5 minutes measured from training initiation to model output availability
4. THE Cache_Layer SHALL reduce the mean API response time, measured over a minimum sample of 100 sequential requests to the same endpoint, by at least 50% compared to the same requests served directly from the database without caching
5. IF the API_Gateway receives more than 100 concurrent client connections, THEN THE API_Gateway SHALL reject additional connections with an error indicating capacity exceeded while maintaining response time thresholds for the existing 100 connections
6. WHEN performance benchmarks are executed, THE system SHALL measure response times under warm conditions after at least 10 prior requests to eliminate cold-start variance from results

### Requirement 17: Scheduled News Fetching via Marketaux API

**User Story:** As a system operator, I want the application to automatically fetch gold-related financial news from the Marketaux API on a recurring schedule, so that the dashboard always displays recent and relevant market news without manual intervention.

#### Acceptance Criteria

1. THE Task_Queue SHALL schedule the News_Fetcher to execute once every 4 hours, starting from application boot, with the interval configurable via an environment variable (NEWS_FETCH_INTERVAL_HOURS) accepting integer values between 1 and 12
2. WHEN the News_Fetcher executes, THE News_Fetcher SHALL send a GET request to the Marketaux_API at /v1/news/all with query parameters: api_token set to the configured API key, search set to the configured keywords (default: "gold,XAU,commodities"), and limit set to 30
3. WHEN the Marketaux_API returns a successful response (HTTP 200), THE News_Fetcher SHALL parse the JSON payload and extract from each article in the "data" array: title, source, url, published_at (ISO 8601), description (first 300 characters), and the entities sentiment_score value for the matched keyword
4. IF the Marketaux_API does not include a sentiment_score for an article or the entities array is empty, THEN THE News_Fetcher SHALL assign a Sentiment_Score of 0.0 (neutral) to that article
5. WHEN the News_Fetcher successfully parses articles, THE News_Fetcher SHALL store the complete parsed array of News_Articles directly into the News_Cache (Redis) with a time-to-live of 5 hours to ensure overlap with the 4-hour fetch cycle
6. WHEN new articles are stored in the News_Cache, THE News_Fetcher SHALL replace the previous cached set entirely rather than appending to it
7. IF the Marketaux_API is unreachable or returns an HTTP error status (4xx or 5xx), THEN THE News_Fetcher SHALL retry the request up to 3 times with exponential backoff starting at a 5-second base delay
8. IF all 3 retry attempts fail, THEN THE News_Fetcher SHALL log an error with the timestamp, HTTP status code (if available), and error message, and SHALL retain the previously cached News_Articles without modification
9. IF the Marketaux_API returns a response containing zero articles in the "data" array, THEN THE News_Fetcher SHALL retain the previously cached News_Articles and log a warning indicating an empty response was received
10. WHEN the News_Fetcher completes successfully, THE News_Fetcher SHALL log the fetch timestamp and the number of articles retrieved

### Requirement 18: News API Endpoint

**User Story:** As a frontend developer, I want a REST API endpoint that returns cached gold-related news articles as a clean flattened JSON array, so that the dashboard can display current market news to users.

#### Acceptance Criteria

1. WHEN a GET request is received at /api/v1/news/gold/, THE News_API_Endpoint SHALL return a JSON response containing an array of News_Article objects ordered by publication timestamp descending (most recent first)
2. THE News_API_Endpoint SHALL serve a clean, flattened JSON array where each News_Article object contains: title (string, mapped from Marketaux "title"), source_name (string, mapped from Marketaux "source"), source_url (string, mapped from Marketaux "url"), published_at (ISO 8601 timestamp, mapped from Marketaux "published_at"), description (string, maximum 300 characters, mapped from Marketaux "description"), sentiment_score (numeric, mapped from Marketaux entities sentiment_score), and sentiment_label (string: "positive", "neutral", or "negative")
3. WHEN the request includes an optional query parameter limit (integer, 1 to 30), THE News_API_Endpoint SHALL return at most that number of articles; WHEN no limit parameter is provided, THE News_API_Endpoint SHALL return all cached articles up to a maximum of 30
4. THE News_API_Endpoint SHALL derive the sentiment_label from the sentiment_score on the backend: "positive" when score is greater than 0.2, "negative" when score is less than -0.2, and "neutral" when score is between -0.2 and 0.2 inclusive
5. WHILE the News_Cache contains valid (non-expired) data, THE News_API_Endpoint SHALL serve the response directly from the News_Cache without triggering a new fetch from the Marketaux_API
6. THE News_API_Endpoint SHALL respond within 200 milliseconds under normal load (fewer than 100 concurrent requests) when serving from cache
7. IF the News_Cache is empty or expired and no previously cached data exists, THEN THE News_API_Endpoint SHALL return an empty JSON array with HTTP status 200 and a message field indicating that news data is being fetched
8. IF the limit query parameter is not a valid integer or is outside the range 1 to 30, THEN THE News_API_Endpoint SHALL return HTTP status 400 with an error message indicating the valid range for the limit parameter
9. THE News_API_Endpoint SHALL include a last_updated field in the response metadata containing the ISO 8601 timestamp of when the cached data was last refreshed

### Requirement 19: News API Provider Configuration

**User Story:** As a system operator, I want the Marketaux API provider to be configurable via environment variables, so that I can update API keys or adjust parameters without code changes.

#### Acceptance Criteria

1. THE News_Fetcher SHALL read the Marketaux API base URL from an environment variable (NEWS_API_BASE_URL) with a default value of "https://api.marketaux.com"
2. THE News_Fetcher SHALL read the Marketaux API authentication token from an environment variable (NEWS_API_KEY)
3. IF the NEWS_API_KEY environment variable is not set or is empty at application startup, THEN THE News_Fetcher SHALL log an error indicating the missing configuration and SHALL not schedule any fetch tasks until the configuration is provided
4. THE News_Fetcher SHALL support configurable query keywords via an environment variable (NEWS_API_KEYWORDS) accepting a comma-separated list of search terms, with a default value of "gold,XAU,commodities"
5. WHEN the NEWS_API_KEYWORDS variable is updated, THE News_Fetcher SHALL use the new keywords on the next scheduled fetch without requiring an application restart

### Requirement 20: Frontend Market Insights Panel Display

**User Story:** As a user, I want to see gold-related financial news on the dashboard in a Market Insights component, so that I can understand the macro-economic context behind gold price movements.

#### Acceptance Criteria

1. WHEN the Dashboard loads, THE Market_Insights_Panel SHALL fetch and display News_Articles from the News_API_Endpoint
2. THE Market_Insights_Panel SHALL display each News_Article as a card containing: the title (as a clickable link opening the source_url in a new browser tab), the source_name, the relative publication time (e.g., "2 hours ago"), and a dynamic Tailwind CSS Sentiment_Label badge
3. THE Market_Insights_Panel SHALL render the Sentiment_Label badge using Tailwind CSS classes with the following colors: green background (bg-green-100 text-green-800) for "positive", gray background (bg-gray-100 text-gray-800) for "neutral", and red background (bg-red-100 text-red-800) for "negative"
4. THE Market_Insights_Panel SHALL display articles ordered by publication timestamp descending (most recent first)
5. THE Market_Insights_Panel SHALL display a maximum of 10 articles by default, with a "Show More" button that loads additional articles up to the full cached set of 30
6. WHILE the Market_Insights_Panel is fetching data from the News_API_Endpoint, THE Market_Insights_Panel SHALL display a loading skeleton with placeholder card shapes matching the expected layout
7. IF the News_API_Endpoint returns an empty array, THEN THE Market_Insights_Panel SHALL display a message indicating that no news is currently available
8. IF the Market_Insights_Panel fails to fetch data from the News_API_Endpoint due to a network error or timeout (exceeding 10 seconds), THEN THE Market_Insights_Panel SHALL display an error message with a retry button that re-initiates the fetch when activated

### Requirement 21: Frontend Market Insights Panel Responsiveness

**User Story:** As a user, I want the Market Insights panel to work well on different screen sizes, so that I can view market news on both desktop and mobile devices.

#### Acceptance Criteria

1. WHILE the viewport width is 1024 pixels or greater, THE Market_Insights_Panel SHALL render as a sidebar positioned to the right of the main chart area, occupying no more than 30% of the viewport width
2. WHILE the viewport width is less than 1024 pixels, THE Market_Insights_Panel SHALL render as a full-width section below the main chart area
3. THE Market_Insights_Panel SHALL use Tailwind CSS utility classes for all styling, consistent with the existing Dashboard styling approach
4. THE Market_Insights_Panel SHALL truncate title text that exceeds 2 lines with an ellipsis indicator, and SHALL display the full title in a tooltip on hover
5. THE Market_Insights_Panel SHALL render the description text truncated to 100 characters with an ellipsis, expandable to the full 300 characters when the user clicks an "expand" control on the card

### Requirement 22: News Data Freshness Indicator

**User Story:** As a user, I want to know how recent the displayed news is, so that I can assess whether the information is current.

#### Acceptance Criteria

1. THE Market_Insights_Panel SHALL display a "Last updated" timestamp at the top of the panel showing the last_updated value from the News_API_Endpoint response, formatted as a relative time (e.g., "Updated 15 minutes ago")
2. WHILE the last_updated timestamp is older than 6 hours, THE Market_Insights_Panel SHALL display a warning indicator (amber-colored icon) next to the "Last updated" text indicating the news data may be stale
3. WHEN the User clicks a refresh button on the Market_Insights_Panel, THE Market_Insights_Panel SHALL re-fetch data from the News_API_Endpoint and update the display
4. WHILE a manual refresh is in progress, THE Market_Insights_Panel SHALL display a loading spinner on the refresh button and disable the button until the fetch completes or fails

### Requirement 23: Error Handling for News Pipeline

**User Story:** As a system operator, I want the news pipeline to handle errors gracefully, so that failures in news fetching do not affect the core gold price prediction functionality.

#### Acceptance Criteria

1. IF the News_Fetcher encounters an unhandled exception during execution, THEN THE News_Fetcher SHALL log the full exception details (stack trace, timestamp, and context) and SHALL terminate the current fetch run without affecting other scheduled Celery tasks
2. IF the News_Cache (Redis) is unreachable when the News_Fetcher attempts to store articles, THEN THE News_Fetcher SHALL log an error and discard the fetched articles for that run without retrying the cache write
3. IF the News_Cache (Redis) is unreachable when the News_API_Endpoint receives a request, THEN THE News_API_Endpoint SHALL return an empty JSON array with HTTP status 200 and a message field indicating news is temporarily unavailable
4. THE News_Fetcher SHALL operate independently from the Data_Ingestion_Pipeline and ML_Training_Pipeline such that a failure in the News_Fetcher does not delay, block, or affect the execution of price data ingestion or model training tasks
5. IF the Marketaux_API returns malformed JSON that cannot be parsed, THEN THE News_Fetcher SHALL log a parsing error with the raw response size and first 500 characters of the response body, and SHALL retain the previously cached News_Articles
6. IF a News_Article from the Marketaux_API response is missing a required field (title or url), THEN THE News_Fetcher SHALL skip that article and log a warning indicating the skipped article and the missing field name

### Requirement 24: News API Security and Sanitization

**User Story:** As a system operator, I want the news endpoint to follow the same security standards as existing API endpoints and sanitize external content, so that the application remains protected from abuse and injection attacks.

#### Acceptance Criteria

1. THE News_API_Endpoint SHALL enforce the same rate limiting policy as other API_Gateway endpoints: 100 requests per fixed 60-second window per IP address
2. IF a client exceeds the rate limit on the News_API_Endpoint, THEN THE API_Gateway SHALL return HTTP status 429 with a Retry-After header indicating the number of seconds remaining until the current rate limit window resets
3. THE News_API_Endpoint SHALL enforce CORS headers allowing requests only from the configured frontend origin domain
4. THE News_API_Endpoint SHALL include security headers in all responses: X-Content-Type-Options set to nosniff, X-Frame-Options set to DENY, and Strict-Transport-Security with a max-age of at least 31536000 seconds
5. THE News_API_Endpoint SHALL sanitize all News_Article text fields (title, description, source_name) by stripping HTML tags and script content before including them in the JSON response
