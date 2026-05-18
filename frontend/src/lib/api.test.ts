import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  APIClient,
  APIError,
  RateLimitError,
  ServiceUnavailableError,
} from "./api";

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("APIClient", () => {
  let client: APIClient;

  beforeEach(() => {
    client = new APIClient("http://localhost:8000", 3, 10000);
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("fetchWithRetry", () => {
    it("returns parsed JSON on successful response", async () => {
      const data = [{ date: "2024-01-01", close: 2050.0 }];
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(data),
      });

      const result = await client.fetchWithRetry("http://localhost:8000/test");
      expect(result).toEqual(data);
    });

    it("throws RateLimitError on 429 response with retryAfter", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 429,
        headers: new Headers({ "Retry-After": "30" }),
        json: () => Promise.resolve({ detail: "Rate limited" }),
      });

      try {
        await client.fetchWithRetry("http://localhost:8000/test");
        expect.fail("Should have thrown");
      } catch (e) {
        expect(e).toBeInstanceOf(RateLimitError);
        expect((e as RateLimitError).retryAfter).toBe(30);
        expect((e as RateLimitError).status).toBe(429);
      }
    });

    it("throws ServiceUnavailableError on 503 response", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 503,
        headers: new Headers(),
        json: () => Promise.resolve({ detail: "Unavailable" }),
      });

      await expect(
        client.fetchWithRetry("http://localhost:8000/test")
      ).rejects.toThrow(ServiceUnavailableError);
    });

    it("throws APIError on other HTTP errors", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: new Headers(),
        json: () => Promise.resolve({ detail: "Bad request" }),
      });

      await expect(
        client.fetchWithRetry("http://localhost:8000/test")
      ).rejects.toThrow(APIError);

      try {
        mockFetch.mockResolvedValueOnce({
          ok: false,
          status: 400,
          headers: new Headers(),
          json: () => Promise.resolve({ detail: "Bad request" }),
        });
        await client.fetchWithRetry("http://localhost:8000/test");
      } catch (e) {
        expect(e).toBeInstanceOf(APIError);
        expect((e as APIError).status).toBe(400);
      }
    });

    it("retries on network errors (TypeError) up to maxRetries", async () => {
      mockFetch
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"));

      await expect(
        client.fetchWithRetry("http://localhost:8000/test")
      ).rejects.toThrow(TypeError);

      // Should have been called 4 times (initial + 3 retries)
      expect(mockFetch).toHaveBeenCalledTimes(4);
    });

    it("succeeds after retrying on network error", async () => {
      const data = { success: true };
      mockFetch
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockRejectedValueOnce(new TypeError("Failed to fetch"))
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: () => Promise.resolve(data),
        });

      const result = await client.fetchWithRetry("http://localhost:8000/test");
      expect(result).toEqual(data);
      expect(mockFetch).toHaveBeenCalledTimes(3);
    });

    it("does not retry on non-network errors", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        headers: new Headers(),
        json: () => Promise.resolve({ detail: "Internal error" }),
      });

      await expect(
        client.fetchWithRetry("http://localhost:8000/test")
      ).rejects.toThrow(APIError);

      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("uses AbortSignal.timeout for request timeout", async () => {
      const data = { ok: true };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(data),
      });

      await client.fetchWithRetry("http://localhost:8000/test");

      const callArgs = mockFetch.mock.calls[0];
      expect(callArgs[1]).toHaveProperty("signal");
    });
  });

  describe("getHistoricalPrices", () => {
    it("calls correct URL without params", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
      });

      await client.getHistoricalPrices();
      expect(mockFetch.mock.calls[0][0]).toBe(
        "http://localhost:8000/api/v1/prices/historical"
      );
    });

    it("calls correct URL with date params", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
      });

      await client.getHistoricalPrices("2024-01-01", "2024-06-01");
      expect(mockFetch.mock.calls[0][0]).toBe(
        "http://localhost:8000/api/v1/prices/historical?start_date=2024-01-01&end_date=2024-06-01"
      );
    });
  });

  describe("getPredictions", () => {
    it("calls correct URL", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
      });

      await client.getPredictions();
      expect(mockFetch.mock.calls[0][0]).toBe(
        "http://localhost:8000/api/v1/prices/predictions"
      );
    });
  });

  describe("getModelMetadata", () => {
    it("calls correct URL", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            training_date: "2024-01-15T02:30:00Z",
            mean_absolute_error: 12.45,
            root_mean_squared_error: 18.72,
            number_of_training_samples: 1257,
            model_version: "v2024-01-15",
          }),
      });

      const result = await client.getModelMetadata();
      expect(result.model_version).toBe("v2024-01-15");
      expect(mockFetch.mock.calls[0][0]).toBe(
        "http://localhost:8000/api/v1/model/metadata"
      );
    });
  });

  describe("getNews", () => {
    it("calls correct URL without limit", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({ last_updated: "2024-01-15T14:30:00Z", articles: [] }),
      });

      await client.getNews();
      expect(mockFetch.mock.calls[0][0]).toBe(
        "http://localhost:8000/api/v1/news/gold/"
      );
    });

    it("calls correct URL with limit", async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({ last_updated: "2024-01-15T14:30:00Z", articles: [] }),
      });

      await client.getNews(10);
      expect(mockFetch.mock.calls[0][0]).toBe(
        "http://localhost:8000/api/v1/news/gold/?limit=10"
      );
    });
  });
});

describe("Error classes", () => {
  it("APIError has correct properties", () => {
    const error = new APIError(404, { detail: "Not found" });
    expect(error.status).toBe(404);
    expect(error.body).toEqual({ detail: "Not found" });
    expect(error.name).toBe("APIError");
    expect(error).toBeInstanceOf(Error);
  });

  it("RateLimitError has correct properties", () => {
    const error = new RateLimitError(45);
    expect(error.status).toBe(429);
    expect(error.retryAfter).toBe(45);
    expect(error.name).toBe("RateLimitError");
    expect(error).toBeInstanceOf(APIError);
  });

  it("ServiceUnavailableError has correct properties", () => {
    const error = new ServiceUnavailableError();
    expect(error.status).toBe(503);
    expect(error.name).toBe("ServiceUnavailableError");
    expect(error).toBeInstanceOf(APIError);
  });
});
