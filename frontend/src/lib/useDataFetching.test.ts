import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useDataFetching, classifyError } from "./useDataFetching";
import { RateLimitError, ServiceUnavailableError, APIError } from "./api";

describe("classifyError", () => {
  it("classifies TypeError as timeout", () => {
    const result = classifyError(new TypeError("Failed to fetch"));
    expect(result.type).toBe("timeout");
    expect(result.message).toContain("timed out");
  });

  it("classifies AbortError DOMException as timeout", () => {
    const err = new DOMException("The operation was aborted", "AbortError");
    const result = classifyError(err);
    expect(result.type).toBe("timeout");
  });

  it("classifies TimeoutError DOMException as timeout", () => {
    const err = new DOMException("Signal timed out", "TimeoutError");
    const result = classifyError(err);
    expect(result.type).toBe("timeout");
  });

  it("classifies ServiceUnavailableError as unavailable", () => {
    const result = classifyError(new ServiceUnavailableError());
    expect(result.type).toBe("unavailable");
    expect(result.message).toContain("temporarily unavailable");
  });

  it("classifies RateLimitError as rate-limited with retryAfter", () => {
    const result = classifyError(new RateLimitError(30));
    expect(result.type).toBe("rate-limited");
    expect(result.retryAfter).toBe(30);
    expect(result.message).toContain("Too many requests");
  });

  it("classifies APIError as generic", () => {
    const result = classifyError(new APIError(500, { message: "Internal error" }));
    expect(result.type).toBe("generic");
    expect(result.message).toContain("Something went wrong");
  });

  it("classifies unknown errors as generic", () => {
    const result = classifyError(new Error("Unknown"));
    expect(result.type).toBe("generic");
  });
});

describe("useDataFetching", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("fetches data successfully", async () => {
    const fetcher = vi.fn().mockResolvedValue({ items: [1, 2, 3] });

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    // Initially no data, not loading
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.isInitialLoad).toBe(true);

    // Trigger fetch
    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.data).toEqual({ items: [1, 2, 3] });
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.consecutiveFailures).toBe(0);
    expect(result.current.isPersistentFailure).toBe(false);
  });

  it("preserves previously loaded data on refresh failure (Req 14.4)", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce({ items: [1, 2, 3] })
      .mockRejectedValueOnce(new APIError(500, null));

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    // First fetch succeeds
    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.data).toEqual({ items: [1, 2, 3] });

    // Second fetch fails - data should be preserved
    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.data).toEqual({ items: [1, 2, 3] });
    expect(result.current.error).not.toBeNull();
    expect(result.current.error!.type).toBe("generic");
  });

  it("shows full-page error state when initial load fails with no prior data (Req 14.5)", async () => {
    const fetcher = vi.fn().mockRejectedValue(new ServiceUnavailableError());

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    expect(result.current.isInitialLoad).toBe(true);

    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.data).toBeNull();
    expect(result.current.error).not.toBeNull();
    expect(result.current.error!.type).toBe("unavailable");
    // isInitialLoad should still be true since no data was ever loaded
    expect(result.current.isInitialLoad).toBe(true);
  });

  it("tracks consecutive failures and sets persistent failure after 3 retries (Req 14.6)", async () => {
    const fetcher = vi.fn().mockRejectedValue(new APIError(500, null));

    const { result } = renderHook(() =>
      useDataFetching({ fetcher, maxRetries: 3 })
    );

    // First failure
    await act(async () => {
      result.current.fetch();
    });
    expect(result.current.consecutiveFailures).toBe(1);
    expect(result.current.isPersistentFailure).toBe(false);

    // Second failure
    await act(async () => {
      result.current.fetch();
    });
    expect(result.current.consecutiveFailures).toBe(2);
    expect(result.current.isPersistentFailure).toBe(false);

    // Third failure - should trigger persistent failure
    await act(async () => {
      result.current.fetch();
    });
    expect(result.current.consecutiveFailures).toBe(3);
    expect(result.current.isPersistentFailure).toBe(true);
  });

  it("resets consecutive failures on successful fetch", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new APIError(500, null))
      .mockRejectedValueOnce(new APIError(500, null))
      .mockResolvedValueOnce({ data: "success" });

    const { result } = renderHook(() =>
      useDataFetching({ fetcher, maxRetries: 3 })
    );

    // Two failures
    await act(async () => {
      result.current.fetch();
    });
    await act(async () => {
      result.current.fetch();
    });
    expect(result.current.consecutiveFailures).toBe(2);

    // Success resets counter
    await act(async () => {
      result.current.fetch();
    });
    expect(result.current.consecutiveFailures).toBe(0);
    expect(result.current.isPersistentFailure).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("auto-retries on rate limit after Retry-After period (Req 14.3)", async () => {
    const fetcher = vi
      .fn()
      .mockRejectedValueOnce(new RateLimitError(5))
      .mockResolvedValueOnce({ data: "after-retry" });

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    // First call triggers rate limit
    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.error).not.toBeNull();
    expect(result.current.error!.type).toBe("rate-limited");
    expect(fetcher).toHaveBeenCalledTimes(1);

    // Advance time past the Retry-After period (5 seconds) and flush promises
    await act(async () => {
      vi.advanceTimersByTime(5000);
      // Allow microtasks (the async fetch) to resolve
      await Promise.resolve();
    });

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(result.current.data).toEqual({ data: "after-retry" });
    expect(result.current.error).toBeNull();
  });

  it("classifies timeout errors correctly (Req 14.3)", async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.error).not.toBeNull();
    expect(result.current.error!.type).toBe("timeout");
  });

  it("classifies 503 errors correctly (Req 14.2)", async () => {
    const fetcher = vi.fn().mockRejectedValue(new ServiceUnavailableError());

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.error).not.toBeNull();
    expect(result.current.error!.type).toBe("unavailable");
  });

  it("dismissError clears the error state", async () => {
    const fetcher = vi.fn().mockRejectedValue(new APIError(500, null));

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    await act(async () => {
      result.current.fetch();
    });

    expect(result.current.error).not.toBeNull();

    act(() => {
      result.current.dismissError();
    });

    expect(result.current.error).toBeNull();
  });

  it("sets loading to true during fetch and false after", async () => {
    let resolvePromise: (value: unknown) => void;
    const fetcher = vi.fn().mockImplementation(
      () => new Promise((resolve) => { resolvePromise = resolve; })
    );

    const { result } = renderHook(() =>
      useDataFetching({ fetcher })
    );

    expect(result.current.loading).toBe(false);

    act(() => {
      result.current.fetch();
    });

    expect(result.current.loading).toBe(true);

    await act(async () => {
      resolvePromise!({ data: "done" });
    });

    expect(result.current.loading).toBe(false);
  });
});
