"use client";

import React from "react";
import type { FetchError } from "../lib/useDataFetching";

export interface ErrorNotificationProps {
  /** The error to display */
  error: FetchError;
  /** Whether this is a persistent failure (3+ consecutive retries) */
  isPersistent?: boolean;
  /** Callback to retry the operation */
  onRetry?: () => void;
  /** Callback to dismiss the notification */
  onDismiss?: () => void;
}

/**
 * Inline error notification banner displayed when a refresh fails
 * but previously loaded data is still being shown.
 *
 * Shows a non-intrusive notification at the top of the content area
 * with the error message and optional retry/dismiss actions.
 *
 * For persistent failures (3+ consecutive retries), shows a stronger
 * warning that the data may be stale.
 *
 * Validates: Requirements 14.1, 14.4, 14.6
 */
export function ErrorNotification({
  error,
  isPersistent = false,
  onRetry,
  onDismiss,
}: ErrorNotificationProps) {
  const bgColor = isPersistent
    ? "bg-amber-50 border-amber-300"
    : "bg-yellow-50 border-yellow-200";
  const textColor = isPersistent ? "text-amber-800" : "text-yellow-800";
  const iconColor = isPersistent ? "text-amber-500" : "text-yellow-500";

  return (
    <div
      role="alert"
      aria-live="polite"
      className={`flex items-center gap-3 rounded-lg border p-3 ${bgColor}`}
    >
      {/* Warning icon */}
      <svg
        className={`h-5 w-5 flex-shrink-0 ${iconColor}`}
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
        />
      </svg>

      <div className="flex-1 min-w-0">
        <p className={`text-sm ${textColor}`}>
          {isPersistent
            ? "Unable to refresh data after multiple attempts. Displayed data may be outdated."
            : error.message}
        </p>
      </div>

      <div className="flex items-center gap-2 flex-shrink-0">
        {onRetry && !isPersistent && (
          <button
            type="button"
            onClick={onRetry}
            className={`text-xs font-medium ${textColor} hover:underline`}
            aria-label="Retry"
          >
            Retry
          </button>
        )}
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className={`${textColor} hover:opacity-70`}
            aria-label="Dismiss notification"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
