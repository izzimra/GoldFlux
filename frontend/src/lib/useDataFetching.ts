"use client";

import { useCallback, useRef, useState } from "react";
import { RateLimitError, ServiceUnavailableError, APIError } from "./api";

/**
 * Error type classification for the error state hierarchy.
 *
 * Priority order (highest to lowest):
 * 1. timeout - Network timeout (>10s)
 * 2. unavailable - 503 Service Unavailable
 * 3. rate-limited - 429 Rate Limited
 * 4. generic - Other errors
 */
export type ErrorType = "timeout" | "unavailable" | "rate-limited" | "generic";

export interface FetchError {
  type: ErrorType;
  message: string;
  retryAfter?: number; // seconds, for rate-limited errors
}

export interface UseDataFetchingOptions<T> {
  /** The async function that fetches data */
  fetcher: () => Promise<T>;
  /** Maximum consecutive retries before showing persistent failure (default: 3) */
  maxRetries?: number;
}

export interface UseDataFetchingResult<T> {
  /** The fetched data, preserved across refresh failures */
  data: T | null;
  /** Whether the initial load or a refresh is in progress */
  loading: boolean;
  /** Current error state, null if no error */
  error: FetchError | null;
  /** Whether this is the initial load (no prior data) */
  isInitialLoad: boolean;
  /** Whether the persistent failure state is active (3+ consecutive failures) */
  isPersistentFailure: boolean;
  /** Number of consecutive retry failures */
  consecutiveFailures: number;
  /** Trigger a fetch/retry */
  fetch: () => void;
  /** Reset error state (e.g., after dismissing a notification) */
  dismissError: () => void;
}

/**
 * Classifies an error into the error state hierarchy.
 *
 * Error State Hierarchy (Frontend):
 * 1. Network timeout (>10s): Show timeout message + retry button
 * 2. 503 Service Unavailable: Show "temporarily unavailable" message
 * 3. 429 Rate Limited: Show "too many requests" + auto-retry after Retry-After
 * 4. Other errors with existing data: Preserve displayed data + show error notification
 * 5. Other errors without existing data: Full-page error state + retry button
 * 6. 3 consecutive retry failures: Show persistent failure message
 *
 * Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
 */
export function classifyError(error: unknown): FetchError {
  // Timeout errors: AbortError from AbortSignal.timeout or TypeError from network issues
  if (error instanceof DOMException && error.name === "AbortError") {
    return {
      type: "timeout",
      message: "The request timed out. Please check your connection and try again.",
    };
  }

  // TypeError from fetch typically indicates network failure / timeout
  if (error instanceof TypeError) {
    return {
      type: "timeout",
      message: "The request timed out. Please check your connection and try again.",
    };
  }

  // TimeoutError (newer browsers)
  if (error instanceof DOMException && error.name === "TimeoutError") {
    return {
      type: "timeout",
      message: "The request timed out. Please check your connection and try again.",
    };
  }

  // 503 Service Unavailable
  if (error instanceof ServiceUnavailableError) {
    return {
      type: "unavailable",
      message: "The service is temporarily unavailable. Please try again later.",
    };
  }

  // 429 Rate Limited
  if (error instanceof RateLimitError) {
    return {
      type: "rate-limited",
      message: "Too many requests. Please wait before trying again.",
      retryAfter: error.retryAfter,
    };
  }

  // Generic API errors
  if (error instanceof APIError) {
    return {
      type: "generic",
      message: "Something went wrong. Please try again.",
    };
  }

  // Unknown errors
  return {
    type: "generic",
    message: "Something went wrong. Please try again.",
  };
}

/**
 * Custom hook for data fetching with error state hierarchy and retry logic.
 *
 * Implements:
 * - Error classification (timeout → 503 → rate limit → generic)
 * - Data preservation on refresh failure (Req 14.4)
 * - Full-page error on initial load failure with no prior data (Req 14.5)
 * - Up to 3 consecutive retries, then persistent failure message (Req 14.6)
 * - Auto-retry on rate limit after Retry-After period (Req 14.3)
 *
 * Validates: Requirements 14.1, 14.2, 14.3, 14.4, 14.5, 14.6
 */
export function useDataFetching<T>({
  fetcher,
  maxRetries = 3,
}: UseDataFetchingOptions<T>): UseDataFetchingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<FetchError | null>(null);
  const [consecutiveFailures, setConsecutiveFailures] = useState<number>(0);
  const [isPersistentFailure, setIsPersistentFailure] = useState<boolean>(false);

  const hasLoadedOnce = useRef<boolean>(false);
  const rateLimitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isInitialLoad = !hasLoadedOnce.current && data === null;

  const executeFetch = useCallback(async () => {
    setLoading(true);

    // Clear any pending rate-limit auto-retry timer
    if (rateLimitTimerRef.current) {
      clearTimeout(rateLimitTimerRef.current);
      rateLimitTimerRef.current = null;
    }

    try {
      const result = await fetcher();
      setData(result);
      setError(null);
      setConsecutiveFailures(0);
      setIsPersistentFailure(false);
      hasLoadedOnce.current = true;
    } catch (err) {
      const classified = classifyError(err);

      setConsecutiveFailures((prev) => {
        const newCount = prev + 1;
        if (newCount >= maxRetries) {
          setIsPersistentFailure(true);
        }
        return newCount;
      });

      setError(classified);

      // Auto-retry for rate-limited errors after Retry-After period
      if (classified.type === "rate-limited" && classified.retryAfter) {
        const retryMs = classified.retryAfter * 1000;
        rateLimitTimerRef.current = setTimeout(() => {
          rateLimitTimerRef.current = null;
          executeFetch();
        }, retryMs);
      }
    } finally {
      setLoading(false);
    }
  }, [fetcher, maxRetries]);

  const dismissError = useCallback(() => {
    setError(null);
  }, []);

  return {
    data,
    loading,
    error,
    isInitialLoad,
    isPersistentFailure,
    consecutiveFailures,
    fetch: executeFetch,
    dismissError,
  };
}
