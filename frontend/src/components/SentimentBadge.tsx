"use client";

import React from "react";

export type SentimentLabel = "positive" | "neutral" | "negative";

export interface SentimentBadgeProps {
  sentimentLabel: SentimentLabel;
}

const BADGE_STYLES: Record<SentimentLabel, string> = {
  positive: "bg-green-100 text-green-800",
  neutral: "bg-gray-100 text-gray-800",
  negative: "bg-red-100 text-red-800",
};

/**
 * Colored badge component that displays a sentiment label.
 *
 * Validates: Requirements 20.3
 */
export function SentimentBadge({ sentimentLabel }: SentimentBadgeProps) {
  const label = sentimentLabel.charAt(0).toUpperCase() + sentimentLabel.slice(1);

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${BADGE_STYLES[sentimentLabel]}`}
    >
      {label}
    </span>
  );
}
