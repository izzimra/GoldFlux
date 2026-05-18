"use client";

import React from "react";

export interface FreshnessIndicatorProps {
  lastUpdated: string | null;
  onRefresh: () => void;
  isRefreshing: boolean;
}

const STALE_THRESHOLD_MS = 6 * 60 * 60 * 1000; // 6 hours in milliseconds

/**
 * Formats an ISO 8601 timestamp as a relative time string (e.g., "15 minutes ago").
 */
export function formatRelativeTime(isoTimestamp: string): string {
  const now = Date.now();
  const then = new Date(isoTimestamp).getTime();
  const diffMs = now - then;

  if (diffMs < 0) {
    return "just now";
  }

  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (seconds < 60) {
    return "just now";
  }
  if (minutes === 1) {
    return "1 minute ago";
  }
  if (minutes < 60) {
    return `${minutes} minutes ago`;
  }
  if (hours === 1) {
    return "1 hour ago";
  }
  if (hours < 24) {
    return `${hours} hours ago`;
  }
  if (days === 1) {
    return "1 day ago";
  }
  return `${days} days ago`;
}

/**
 * Determines whether the given timestamp is older than 6 hours.
 */
export function isStale(isoTimestamp: string): boolean {
  const now = Date.now();
  const then = new Date(isoTimestamp).getTime();
  return now - then > STALE_THRESHOLD_MS;
}

/**
 * Displays a "Last updated" relative time indicator with a stale warning
 * and a refresh button.
 *
 * Validates: Requirements 22.1, 22.2, 22.3, 22.4
 */
export function FreshnessIndicator({
  lastUpdated,
  onRefresh,
  isRefreshing,
}: FreshnessIndicatorProps) {
  const relativeTime = lastUpdated ? formatRelativeTime(lastUpdated) : null;
  const stale = lastUpdated ? isStale(lastUpdated) : false;

  return (
    <div className="flex items-center gap-2 text-sm text-gray-600">
      {lastUpdated ? (
        <span className="flex items-center gap-1">
          {stale && (
            <svg
              className="w-4 h-4 text-amber-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-label="Stale data warning"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          )}
          <span>Updated {relativeTime}</span>
        </span>
      ) : (
        <span>No update info available</span>
      )}

      <button
        onClick={onRefresh}
        disabled={isRefreshing}
        className={`inline-flex items-center p-1 rounded hover:bg-gray-100 transition-colors ${
          isRefreshing ? "opacity-50 cursor-not-allowed" : ""
        }`}
        aria-label="Refresh news"
      >
        <svg
          className={`w-4 h-4 ${isRefreshing ? "animate-spin" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
          />
        </svg>
      </button>
    </div>
  );
}
