"use client";

import React, { useCallback, useEffect } from "react";
import { apiClient } from "@/lib/api";
import type { HistoricalPrice, Prediction } from "@/lib/api";
import { useDataFetching } from "@/lib/useDataFetching";
import { HistoricalChart } from "@/components/HistoricalChart";
import { PredictionChart } from "@/components/PredictionChart";
import { ModelInfoPanel } from "@/components/ModelInfoPanel";
import { DashboardLayout } from "@/components/MarketInsightsPanel";
import { ErrorState } from "@/components/ErrorState";
import { ErrorNotification } from "@/components/ErrorNotification";
import { LoadingSkeleton } from "@/components/LoadingSkeleton";
import type { ErrorVariant } from "@/components/ErrorState";

/**
 * Shape of the prediction data fetched by the Dashboard.
 * Combines historical prices (for the prediction chart overlay)
 * and prediction records.
 */
interface PredictionData {
  historicalData: HistoricalPrice[];
  predictions: Prediction[];
}

/**
 * Maps a FetchError type to an ErrorState variant.
 */
function errorTypeToVariant(type: string): ErrorVariant {
  switch (type) {
    case "timeout":
      return "timeout";
    case "unavailable":
      return "unavailable";
    default:
      return "generic";
  }
}

/**
 * Dashboard page — main entry point for GoldFlux.
 * Orchestrates data fetching and integrates all components:
 * - HistoricalChart: displays historical gold close prices (self-contained, default 1 month)
 * - PredictionChart: overlays predicted prices with confidence band
 * - ModelInfoPanel: shows model training metrics (self-contained)
 * - MarketInsightsPanel: news sidebar with sentiment badges (via DashboardLayout, self-contained)
 *
 * Error State Hierarchy (via useDataFetching hook):
 * 1. Network timeout (>10s): Show timeout message + retry button
 * 2. 503 Service Unavailable: Show "temporarily unavailable" message
 * 3. 429 Rate Limited: Show "too many requests" + auto-retry after Retry-After
 * 4. Error with existing data: Preserve displayed data + show error notification
 * 5. Error without existing data: Full-page error state + retry button
 * 6. 3 consecutive retry failures: Show persistent failure message
 *
 * Responsive layout:
 * - Desktop (≥1024px): MarketInsightsPanel as sidebar, max 30% viewport width
 * - Mobile (<1024px): MarketInsightsPanel as full-width section below charts
 *
 * Validates: Requirements 9.1, 10.1, 11.3, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 20.1
 */
export default function Dashboard() {
  const fetchPredictionData = useCallback(async (): Promise<PredictionData> => {
    // Fetch historical prices (default 1 month for the prediction chart overlay)
    const now = new Date();
    const oneMonthAgo = new Date(now);
    oneMonthAgo.setMonth(oneMonthAgo.getMonth() - 1);
    const startDate = oneMonthAgo.toISOString().split("T")[0];
    const endDate = now.toISOString().split("T")[0];

    const [prices, predictionsResponse] = await Promise.all([
      apiClient.getHistoricalPrices(startDate, endDate),
      apiClient.getPredictions(),
    ]);

    // Handle both array and object response shapes
    let predictions: Prediction[];
    if (Array.isArray(predictionsResponse)) {
      predictions = predictionsResponse;
    } else if (predictionsResponse.data) {
      predictions = predictionsResponse.data;
    } else {
      predictions = [];
    }

    return { historicalData: prices, predictions };
  }, []);

  const {
    data,
    loading,
    error,
    isInitialLoad,
    isPersistentFailure,
    fetch: fetchData,
    dismissError,
  } = useDataFetching<PredictionData>({
    fetcher: fetchPredictionData,
    maxRetries: 3,
  });

  // Trigger initial fetch on mount
  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Full-page error state: initial load failed with no prior data
  if (!loading && error && !data) {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="border-b border-gray-200 bg-white px-4 py-4 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-bold text-gray-900">GoldFlux</h1>
          <p className="mt-1 text-sm text-gray-500">
            Gold Price Prediction &amp; Market Intelligence
          </p>
        </header>
        <div className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 lg:px-8">
          <div className="flex items-center justify-center min-h-[60vh]">
            <ErrorState
              variant={errorTypeToVariant(error.type)}
              message={
                isPersistentFailure
                  ? "Unable to load data after multiple attempts. Please try again later."
                  : error.message
              }
              onRetry={fetchData}
            />
          </div>
        </div>
      </div>
    );
  }

  // Loading state: initial load in progress with no prior data
  if (loading && isInitialLoad) {
    return (
      <div className="min-h-screen bg-gray-50">
        <header className="border-b border-gray-200 bg-white px-4 py-4 sm:px-6 lg:px-8">
          <h1 className="text-2xl font-bold text-gray-900">GoldFlux</h1>
          <p className="mt-1 text-sm text-gray-500">
            Gold Price Prediction &amp; Market Intelligence
          </p>
        </header>
        <div className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 lg:px-8">
          <DashboardLayout>
            <div className="space-y-6">
              <LoadingSkeleton lines={8} className="rounded-lg border border-gray-200 bg-white p-6" />
              <LoadingSkeleton lines={6} className="rounded-lg border border-gray-200 bg-white p-6" />
              <LoadingSkeleton lines={4} className="rounded-lg border border-gray-200 bg-white p-6" />
            </div>
          </DashboardLayout>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white px-4 py-4 sm:px-6 lg:px-8">
        <h1 className="text-2xl font-bold text-gray-900">GoldFlux</h1>
        <p className="mt-1 text-sm text-gray-500">
          Gold Price Prediction &amp; Market Intelligence
        </p>
      </header>

      {/* Main content with responsive sidebar layout */}
      <div className="mx-auto max-w-screen-2xl px-4 py-6 sm:px-6 lg:px-8">
        <DashboardLayout>
          {/* Chart section */}
          <div className="space-y-6">
            {/* Error notification: refresh failed but data is still displayed */}
            {error && data && (
              <ErrorNotification
                error={error}
                isPersistent={isPersistentFailure}
                onRetry={fetchData}
                onDismiss={dismissError}
              />
            )}

            {/* Historical Chart — self-contained with date range selector */}
            <HistoricalChart />

            {/* Prediction Chart — overlays predictions on historical data */}
            <PredictionChart
              historicalData={data?.historicalData ?? []}
              predictions={data?.predictions ?? []}
            />

            {/* Model Info Panel — self-contained */}
            <ModelInfoPanel />
          </div>
        </DashboardLayout>
      </div>
    </div>
  );
}
