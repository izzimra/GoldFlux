// Centralized API client for GoldFlux frontend
// Handles retries, timeouts, and typed error responses

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --- Error Classes ---

export class APIError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(status: number, body: unknown) {
    super(`API error: ${status}`);
    this.name = "APIError";
    this.status = status;
    this.body = body;
  }
}

export class RateLimitError extends APIError {
  public readonly retryAfter: number;

  constructor(retryAfter: number) {
    super(429, { message: "Rate limit exceeded" });
    this.name = "RateLimitError";
    this.retryAfter = retryAfter;
  }
}

export class ServiceUnavailableError extends APIError {
  constructor() {
    super(503, { message: "Service temporarily unavailable" });
    this.name = "ServiceUnavailableError";
  }
}

// --- Response Types ---

export interface HistoricalPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Prediction {
  predicted_date: string;
  predicted_close_price: number;
  confidence_interval_lower: number;
  confidence_interval_upper: number;
}

export interface PredictionsResponse {
  data?: Prediction[];
  message?: string;
}

export interface ModelMetadata {
  training_date: string;
  mean_absolute_error: number;
  root_mean_squared_error: number;
  number_of_training_samples: number;
  model_version: string;
}

export interface NewsArticle {
  title: string;
  source_name: string;
  source_url: string;
  published_at: string;
  description: string;
  sentiment_score: number;
  sentiment_label: string;
}

export interface NewsResponse {
  last_updated: string;
  articles: NewsArticle[];
  message?: string;
}

// --- API Client ---

export class APIClient {
  private baseUrl: string;
  private maxRetries: number;
  private timeout: number;

  constructor(
    baseUrl: string = API_BASE_URL,
    maxRetries: number = 3,
    timeout: number = 10000
  ) {
    this.baseUrl = baseUrl;
    this.maxRetries = maxRetries;
    this.timeout = timeout;
  }

  /**
   * Fetch with retry logic.
   * - 10-second timeout via AbortSignal.timeout
   * - Up to 3 retries on network errors (TypeError)
   * - Throws RateLimitError on 429, ServiceUnavailableError on 503, APIError on other HTTP errors
   */
  async fetchWithRetry<T>(
    url: string,
    options?: RequestInit
  ): Promise<T> {
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const response = await fetch(url, {
          ...options,
          signal: AbortSignal.timeout(this.timeout),
        });

        if (response.status === 429) {
          const retryAfter = response.headers.get("Retry-After");
          throw new RateLimitError(Number(retryAfter) || 60);
        }

        if (response.status === 503) {
          throw new ServiceUnavailableError();
        }

        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new APIError(response.status, body);
        }

        return (await response.json()) as T;
      } catch (error) {
        // Only retry on network errors (TypeError), not on HTTP errors
        if (error instanceof TypeError) {
          if (attempt === this.maxRetries) throw error;
          continue;
        }
        throw error;
      }
    }

    // This should never be reached, but satisfies TypeScript
    throw new Error("Unexpected: exceeded retry loop");
  }

  /**
   * Fetch historical gold prices.
   * @param startDate - ISO date string (YYYY-MM-DD)
   * @param endDate - ISO date string (YYYY-MM-DD)
   */
  async getHistoricalPrices(
    startDate?: string,
    endDate?: string
  ): Promise<HistoricalPrice[]> {
    const params = new URLSearchParams();
    if (startDate) params.set("start_date", startDate);
    if (endDate) params.set("end_date", endDate);

    const query = params.toString();
    const url = `${this.baseUrl}/api/v1/prices/historical${query ? `?${query}` : ""}`;

    return this.fetchWithRetry<HistoricalPrice[]>(url);
  }

  /**
   * Fetch price predictions.
   */
  async getPredictions(): Promise<Prediction[] | PredictionsResponse> {
    const url = `${this.baseUrl}/api/v1/prices/predictions`;
    return this.fetchWithRetry<Prediction[] | PredictionsResponse>(url);
  }

  /**
   * Fetch model metadata.
   */
  async getModelMetadata(): Promise<ModelMetadata> {
    const url = `${this.baseUrl}/api/v1/model/metadata`;
    return this.fetchWithRetry<ModelMetadata>(url);
  }

  /**
   * Fetch gold-related news articles.
   * @param limit - Number of articles to return (1-30)
   */
  async getNews(limit?: number): Promise<NewsResponse> {
    const params = new URLSearchParams();
    if (limit !== undefined) params.set("limit", String(limit));

    const query = params.toString();
    const url = `${this.baseUrl}/api/v1/news/gold/${query ? `?${query}` : ""}`;

    return this.fetchWithRetry<NewsResponse>(url);
  }
}

// --- Singleton Export ---

export const apiClient = new APIClient();
