import React from "react";

export interface LoadingSkeletonProps {
  /** Number of skeleton lines to render. Defaults to 3. */
  lines?: number;
  /** Additional CSS class names for the container. */
  className?: string;
}

/**
 * Skeleton placeholder component for loading states.
 * Renders animated pulse bars to indicate content is loading.
 *
 * Validates: Requirements 14.1, 14.2, 14.3, 14.5
 */
export function LoadingSkeleton({ lines = 3, className }: LoadingSkeletonProps) {
  return (
    <div
      role="status"
      aria-label="Loading content"
      aria-busy="true"
      className={`animate-pulse space-y-3 ${className || ""}`}
    >
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          className={`h-4 rounded bg-gray-200 ${
            index === lines - 1 ? "w-3/4" : "w-full"
          }`}
        />
      ))}
      <span className="sr-only">Loading...</span>
    </div>
  );
}
