"use client";

import React, { useState } from "react";
import { SentimentBadge } from "./SentimentBadge";
import type { SentimentLabel } from "./SentimentBadge";
import type { NewsArticle } from "../lib/api";

export interface NewsCardProps {
  article: NewsArticle;
}

/**
 * Computes a human-readable relative time string from an ISO 8601 timestamp.
 * E.g., "2 hours ago", "3 days ago", "just now"
 */
export function getRelativeTime(isoTimestamp: string): string {
  const now = Date.now();
  const then = new Date(isoTimestamp).getTime();
  const diffMs = now - then;

  if (diffMs < 0) return "just now";

  const seconds = Math.floor(diffMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const weeks = Math.floor(days / 7);
  const months = Math.floor(days / 30);
  const years = Math.floor(days / 365);

  if (years > 0) return years === 1 ? "1 year ago" : `${years} years ago`;
  if (months > 0) return months === 1 ? "1 month ago" : `${months} months ago`;
  if (weeks > 0) return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  if (days > 0) return days === 1 ? "1 day ago" : `${days} days ago`;
  if (hours > 0) return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  if (minutes > 0) return minutes === 1 ? "1 minute ago" : `${minutes} minutes ago`;
  return "just now";
}

/**
 * Truncates text to a given character limit, appending ellipsis if truncated.
 */
function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength).trimEnd() + "…";
}

/**
 * NewsCard component displays a single news article with:
 * - Title as clickable link (opens source_url in new tab), truncated to 2 lines
 * - Source name and relative publication time
 * - SentimentBadge
 * - Description truncated to 100 chars, expandable to full 300 chars on click
 *
 * Validates: Requirements 20.2, 21.4, 21.5
 */
export function NewsCard({ article }: NewsCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const {
    title,
    source_name,
    source_url,
    published_at,
    description,
    sentiment_label,
  } = article;

  const relativeTime = getRelativeTime(published_at);
  const truncatedDescription = truncateText(description, 100);
  const showExpandButton = description.length > 100;
  const displayDescription = isExpanded ? description : truncatedDescription;

  return (
    <article className="border border-gray-200 rounded-lg p-4 hover:shadow-sm transition-shadow">
      {/* Title as clickable link, truncated to 2 lines */}
      <a
        href={source_url}
        target="_blank"
        rel="noopener noreferrer"
        title={title}
        className="block text-sm font-semibold text-blue-700 hover:text-blue-900 hover:underline line-clamp-2 leading-tight"
      >
        {title}
      </a>

      {/* Meta row: source, time, sentiment */}
      <div className="flex items-center gap-2 mt-2 text-xs text-gray-500">
        <span className="font-medium text-gray-700">{source_name}</span>
        <span aria-label="separator">·</span>
        <time dateTime={published_at}>{relativeTime}</time>
        <SentimentBadge sentimentLabel={sentiment_label as SentimentLabel} />
      </div>

      {/* Description with expand/collapse */}
      {description && (
        <div className="mt-2">
          <p className="text-xs text-gray-600 leading-relaxed">
            {displayDescription}
            {showExpandButton && (
              <button
                type="button"
                onClick={() => setIsExpanded(!isExpanded)}
                className="ml-1 text-blue-600 hover:text-blue-800 font-medium"
              >
                {isExpanded ? "Show less" : "Read more"}
              </button>
            )}
          </p>
        </div>
      )}
    </article>
  );
}
