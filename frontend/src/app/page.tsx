"use client";

import React, { useCallback, useEffect, useState } from "react";
import { apiClient } from "@/lib/api";
import type { HistoricalPrice, Prediction } from "@/lib/api";
import { HistoricalChart } from "@/components/HistoricalChart";
import { PredictionChart } from "@/components/PredictionChart";
import { ModelInfoPanel } from "@/components/ModelInfoPanel";
import { DashboardLayout } from "@/components/MarketInsightsPanel";

/**
 * Dashboard page — main entry point for GoldFlux.
 * Orchestrates data fetching and integrates all components:
 * - HistoricalChart: displays historical gold close prices (default 1 month)
 * - PredictionChart: overlays predicted prices with confidence band
 * - ModelInfoPanel: shows model training metrics
 * - MarketInsightsPanel: news sidebar with sentiment badges (via DashboardLayout)
 *
 * Responsive layout:
 * - Desktop (≥1024px): MarketInsightsPanel as sidebar, max 30% viewport width
 * - Mobile (<1024px): MarketInsightsPanel as full-width section below charts
 *
 * Validates: Requirements 9.1, 10.1, 11.3, 20.1
 */
export default function Dashboard() {
  const [historicalData, setHistoricalData] = useState<HistoricalPrice[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [dataLoading, setDataLoading] = useState(true);

  const fetchPredictionData = useCallback(async () => {
    setDataLoading(true);
    try {
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

      setHistoricalData(prices);

      // Handle both array and object response shapes
      if (Array.isArray(predictionsResponse)) {
        setPredictions(predictionsResponse);
      } else if (predictionsResponse.data) {
        setPredictions(predictionsResponse.data);
      } else {
        setPredictions([]);
      }
    } catch {
      // Individual components handle their own error states;
      // prediction chart will show empty state gracefully
      setHistoricalData([]);
      setPredictions([]);
    } finally {
      setDataLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPredictionData();
  }, [fetchPredictionData]);

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
            {/* Historical Chart — self-contained with date range selector */}
            <HistoricalChart />

            {/* Prediction Chart — overlays predictions on historical data */}
            {!dataLoading && (
              <PredictionChart
                historicalData={historicalData}
                predictions={predictions}
              />
            )}

            {/* Model Info Panel */}
            <ModelInfoPanel />
          </div>
        </DashboardLayout>
      </div>
    </div>
  );
}
