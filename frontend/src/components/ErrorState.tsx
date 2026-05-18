"use client";

import React from "react";

export type ErrorVariant = "timeout" | "unavailable" | "generic";

export interface ErrorStateProps {
  message?: string;
  onRetry?: () => void;
  variant?: ErrorVariant;
}

const DEFAULT_MESSAGES: Record<ErrorVariant, string> = {
  timeout: "The request timed out. Please check your connection and try again.",
  unavailable: "The service is temporarily unavailable. Please try again later.",
  generic: "Something went wrong. Please try again.",
};

/**
 * Reusable error display component with retry button.
 * Supports different messages for timeout, 503/unavailable, and generic errors.
 *
 * Validates: Requirements 14.1, 14.2, 14.3, 14.5
 */
export function ErrorState({
  message,
  onRetry,
  variant = "generic",
}: ErrorStateProps) {
  const displayMessage = message || DEFAULT_MESSAGES[variant];

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex flex-col items-center justify-center rounded-lg border border-red-200 bg-red-50 p-6 text-center"
    >
      <svg
        className="mb-3 h-10 w-10 text-red-400"
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

      <p className="mb-4 text-sm text-red-700">{displayMessage}</p>

      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
          aria-label="Retry"
        >
          Retry
        </button>
      )}
    </div>
  );
}
