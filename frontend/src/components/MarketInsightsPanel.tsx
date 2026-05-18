"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiClient, ServiceUnavailableError } from "../lib/api";
import type { NewsArticle } from "../lib/api";
import { FreshnessIndicator } from "./FreshnessIndicator";
import { NewsCard } from "./NewsCard";
import { LoadingSkeleton } from "./LoadingSkeleton";
import { ErrorState } from "./ErrorState";
import type { ErrorVariant } from "./ErrorState";

const DEFAULT_DISPLAY_COUNT = 10;
const MAX_DISPLAY_COUNT = 30;

/**
 * Determines the ErrorState variant based on the error type.
 */
function getErrorVariant(error: unknown): ErrorVariant {
  if (error instanceof TypeError) {
    // Network errors / timeouts surface as TypeError from fetch
    return "timeout";
  }
  if (error instanceof ServiceUnavailableError) {
    return "unavailable";
  }
  return "generic";
}

/**
 * MarketInsightsPanel displays gold-related financial news articles
 * with sentiment badges, freshness indicator, and pagination.
 *
 * Responsive layout (Validates: Requirements 21.1, 21.2, 21.3):
 * - Desktop (≥1024px): renders as sidebar, max 30% viewport width
 * - Mobile (<1024px): renders as full-width section below chart area
 *
 * Validates: Requirements 20.1, 20.2, 20.4, 20.5, 20.6, 20.7, 20.8
 */
export function MarketInsightsPanel() {
  const [articles, setArticles] = useState<NewsArticle[]>([]);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<unknown>(null);
  const [displayCount, setDisplayCount] = useState<number>(DEFAULT_DISPLAY_COUNT);

  const fetchNews = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.getNews(MAX_DISPLAY_COUNT);
      // Sort articles by published_at descending (most recent first)
      const sorted = [...response.articles].sort(
        (a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime()
      );
      setArticles(sorted);
      setLastUpdated(response.last_updated);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchNews();
  }, [fetchNews]);

  const handleRefresh = useCallback(() => {
    fetchNews();
  }, [fetchNews]);

  const handleShowMore = () => {
    setDisplayCount(MAX_DISPLAY_COUNT);
  };

  // Loading state
  if (loading && articles.length === 0) {
    return (
      <aside
        className="w-full lg:max-w-[30vw] lg:sticky lg:top-4 lg:self-start lg:overflow-y-auto lg:max-h-[calc(100vh-2rem)] space-y-4 p-4"
        aria-label="Market Insights"
      >
        <h2 className="text-lg font-semibold text-gray-900">Market Insights</h2>
        <LoadingSkeleton lines={5} className="mb-3" />
        <LoadingSkeleton lines={5} className="mb-3" />
        <LoadingSkeleton lines={5} />
      </aside>
    );
  }

  // Error state (no data available)
  if (error && articles.length === 0) {
    return (
      <aside
        className="w-full lg:max-w-[30vw] lg:sticky lg:top-4 lg:self-start lg:overflow-y-auto lg:max-h-[calc(100vh-2rem)] space-y-4 p-4"
        aria-label="Market Insights"
      >
        <h2 className="text-lg font-semibold text-gray-900">Market Insights</h2>
        <ErrorState
          variant={getErrorVariant(error)}
          onRetry={fetchNews}
        />
      </aside>
    );
  }

  const visibleArticles = articles.slice(0, displayCount);
  const hasMore = articles.length > displayCount;

  return (
    <aside
      className="w-full lg:max-w-[30vw] lg:sticky lg:top-4 lg:self-start lg:overflow-y-auto lg:max-h-[calc(100vh-2rem)] space-y-4 p-4"
      aria-label="Market Insights"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Market Insights</h2>
        <FreshnessIndicator
          lastUpdated={lastUpdated}
          onRefresh={handleRefresh}
          isRefreshing={loading}
        />
      </div>

      {/* Empty state */}
      {articles.length === 0 && (
        <p className="text-sm text-gray-500 text-center py-6">
          No news is currently available.
        </p>
      )}

      {/* News card list */}
      {visibleArticles.length > 0 && (
        <div className="space-y-3">
          {visibleArticles.map((article, index) => (
            <NewsCard key={`${article.source_url}-${index}`} article={article} />
          ))}
        </div>
      )}

      {/* Show More button */}
      {hasMore && (
        <button
          type="button"
          onClick={handleShowMore}
          className="w-full py-2 text-sm font-medium text-blue-600 hover:text-blue-800 hover:bg-blue-50 rounded-md transition-colors"
        >
          Show More
        </button>
      )}
    </aside>
  );
}

/**
 * DashboardLayout provides the responsive container for the chart area
 * and the MarketInsightsPanel sidebar.
 *
 * - Desktop (≥1024px): flex row with chart area on left, sidebar on right
 * - Mobile (<1024px): flex column with chart area on top, panel below
 *
 * Validates: Requirements 21.1, 21.2, 21.3
 */
export function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col lg:flex-row gap-6 w-full">
      {/* Main chart area: takes remaining space on desktop */}
      <main className="flex-1 min-w-0">
        {children}
      </main>
      {/* Market Insights sidebar: full-width on mobile, max 30vw on desktop */}
      <MarketInsightsPanel />
    </div>
  );
}
