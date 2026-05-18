# Requirements Document

## Introduction

GoldFlux is a production-grade Gold Price Prediction web application that aggregates historical gold market data, trains machine learning models to forecast future prices, and presents predictions alongside historical trends on an interactive dashboard. The system uses a React/Next.js frontend with ApexCharts for visualization, a Django REST Framework backend, PostgreSQL for persistent storage, Redis for caching and task queuing, and Celery for asynchronous ML training and data ingestion pipelines. Market data is sourced from the yfinance library using the GC=F (Gold Futures) ticker.

## Glossary

- **Dashboard**: The primary frontend interface displaying historical gold prices, predicted prices, and model performance metrics
- **Data_Ingestion_Pipeline**: The automated Celery-based process that fetches gold price data from yfinance and stores it in PostgreSQL
- **ML_Training_Pipeline**: The automated Celery-based process that trains or retrains the prediction model on historical data
- **Prediction_Engine**: The component that generates gold price forecasts using the trained ML model
- **API_Gateway**: The Django REST Framework layer that serves historical data, predictions, and model metadata to the frontend
- **Cache_Layer**: The Redis-based caching system that stores frequently accessed API responses and intermediate computation results
- **Task_Queue**: The Celery/Redis-based system that manages asynchronous background jobs for data ingestion and model training
- **Gold_Price_Record**: A single data point containing date, open, high, low, close, and volume for the GC=F ticker
- **Prediction_Record**: A forecasted price data point containing a future date and predicted close price with confidence interval
- **Model_Metadata**: Information about the trained model including training date, accuracy metrics, and hyperparameters
- **User**: A person accessing the GoldFlux dashboard to view gold price data and predictions

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

1. THE API_Gateway SHALL enforce rate limiting of 100 requests per fixed 60-second window per IP address
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
