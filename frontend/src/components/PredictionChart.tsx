"use client";

import React, { useMemo } from "react";
import dynamic from "next/dynamic";
import type { ApexAxisChartSeries } from "apexcharts";
import type { HistoricalPrice, Prediction } from "@/lib/api";

// Dynamically import ApexCharts to avoid SSR issues
const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export interface PredictionChartProps {
  historicalData: HistoricalPrice[];
  predictions: Prediction[];
}

/**
 * PredictionChart component displays predicted gold prices as a dashed line
 * alongside historical data, with a 95% confidence interval shaded band
 * and a vertical marker at the boundary between historical and predicted data.
 *
 * Validates: Requirements 10.1, 10.2, 10.3, 10.4, 10.5
 */
export function PredictionChart({
  historicalData,
  predictions,
}: PredictionChartProps) {
  const hasPredictions = predictions.length > 0;
  const hasHistorical = historicalData.length > 0;

  const { series, options } = useMemo(() => {
    // Historical close prices series
    const historicalSeries = historicalData.map((item) => ({
      x: new Date(item.date).getTime(),
      y: item.close,
    }));

    // Prediction close prices series
    const predictionSeries = predictions.map((item) => ({
      x: new Date(item.predicted_date).getTime(),
      y: item.predicted_close_price,
    }));

    // Confidence interval band (rendered as a range-area)
    const confidenceBandSeries = predictions.map((item) => ({
      x: new Date(item.predicted_date).getTime(),
      y: [item.confidence_interval_lower, item.confidence_interval_upper],
    }));

    // Connect prediction line to last historical point for visual continuity
    if (hasHistorical && hasPredictions) {
      const lastHistorical = historicalData[historicalData.length - 1];
      predictionSeries.unshift({
        x: new Date(lastHistorical.date).getTime(),
        y: lastHistorical.close,
      });
      confidenceBandSeries.unshift({
        x: new Date(lastHistorical.date).getTime(),
        y: [lastHistorical.close, lastHistorical.close],
      });
    }

    // Determine boundary date for vertical marker annotation
    const boundaryDate = hasHistorical
      ? new Date(historicalData[historicalData.length - 1].date).getTime()
      : null;

    const chartSeries: ApexAxisChartSeries = [
      {
        name: "Historical Close",
        type: "line",
        data: historicalSeries,
      },
    ];

    if (hasPredictions) {
      chartSeries.push({
        name: "Predicted Close",
        type: "line",
        data: predictionSeries,
      });
      chartSeries.push({
        name: "95% Confidence Interval",
        type: "rangeArea",
        data: confidenceBandSeries,
      });
    }

    const chartOptions: ApexCharts.ApexOptions = {
      chart: {
        type: "line",
        height: 400,
        toolbar: { show: true },
        zoom: { enabled: true },
      },
      stroke: {
        width: [2, 2, 0],
        dashArray: [0, 5, 0],
        curve: "smooth",
      },
      colors: ["#3b82f6", "#f59e0b", "#f59e0b"],
      fill: {
        type: ["solid", "solid", "solid"],
        opacity: [1, 1, 0.15],
      },
      xaxis: {
        type: "datetime",
        labels: {
          format: "MMM dd, yyyy",
        },
        title: { text: "Date" },
      },
      yaxis: {
        title: { text: "Price (USD)" },
        labels: {
          formatter: (val: number) => `$${val.toFixed(2)}`,
        },
      },
      tooltip: {
        shared: false,
        custom: function ({ seriesIndex, dataPointIndex, w }) {
          const seriesName = w.config.series[seriesIndex].name;
          const dataPoint = w.config.series[seriesIndex].data[dataPointIndex];

          if (!dataPoint) return "";

          const date = new Date(dataPoint.x).toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
          });

          if (seriesName === "Historical Close") {
            // Find the matching historical data point for full OHLCV
            const matchingHistorical = historicalData.find(
              (h) => new Date(h.date).getTime() === dataPoint.x
            );
            if (matchingHistorical) {
              return `<div class="p-2 text-sm">
                <div class="font-semibold mb-1">${date}</div>
                <div>Open: $${matchingHistorical.open.toFixed(2)}</div>
                <div>High: $${matchingHistorical.high.toFixed(2)}</div>
                <div>Low: $${matchingHistorical.low.toFixed(2)}</div>
                <div>Close: $${matchingHistorical.close.toFixed(2)}</div>
                <div>Volume: ${matchingHistorical.volume.toLocaleString()}</div>
              </div>`;
            }
            return `<div class="p-2 text-sm">
              <div class="font-semibold mb-1">${date}</div>
              <div>Close: $${dataPoint.y.toFixed(2)}</div>
            </div>`;
          }

          if (seriesName === "Predicted Close") {
            // Find matching prediction for CI values
            const matchingPrediction = predictions.find(
              (p) => new Date(p.predicted_date).getTime() === dataPoint.x
            );
            if (matchingPrediction) {
              return `<div class="p-2 text-sm">
                <div class="font-semibold mb-1">${date}</div>
                <div>Predicted Close: $${matchingPrediction.predicted_close_price.toFixed(2)}</div>
                <div>CI Lower: $${matchingPrediction.confidence_interval_lower.toFixed(2)}</div>
                <div>CI Upper: $${matchingPrediction.confidence_interval_upper.toFixed(2)}</div>
              </div>`;
            }
            return `<div class="p-2 text-sm">
              <div class="font-semibold mb-1">${date}</div>
              <div>Predicted Close: $${dataPoint.y.toFixed(2)}</div>
            </div>`;
          }

          // Confidence interval tooltip
          if (seriesName === "95% Confidence Interval" && Array.isArray(dataPoint.y)) {
            return `<div class="p-2 text-sm">
              <div class="font-semibold mb-1">${date}</div>
              <div>CI Lower: $${dataPoint.y[0].toFixed(2)}</div>
              <div>CI Upper: $${dataPoint.y[1].toFixed(2)}</div>
            </div>`;
          }

          return "";
        },
      },
      legend: {
        show: true,
        position: "top",
      },
      annotations: boundaryDate
        ? {
            xaxis: [
              {
                x: boundaryDate,
                borderColor: "#6b7280",
                strokeDashArray: 4,
                label: {
                  text: "Forecast Start",
                  style: {
                    color: "#374151",
                    background: "#f3f4f6",
                    fontSize: "11px",
                    padding: {
                      left: 6,
                      right: 6,
                      top: 2,
                      bottom: 2,
                    },
                  },
                  position: "top",
                },
              },
            ],
          }
        : undefined,
      dataLabels: {
        enabled: false,
      },
    };

    return { series: chartSeries, options: chartOptions };
  }, [historicalData, predictions, hasHistorical, hasPredictions]);

  if (!hasHistorical && !hasPredictions) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-gray-200 bg-gray-50 p-8">
        <p className="text-sm text-gray-500">No data available to display.</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <h2 className="mb-4 text-lg font-semibold text-gray-900">
        Gold Price &amp; Predictions
      </h2>

      {!hasPredictions && (
        <div className="mb-3 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700">
          Predictions are not yet available. Showing historical data only.
        </div>
      )}

      <Chart
        options={options}
        series={series}
        type="line"
        height={400}
        width="100%"
      />
    </div>
  );
}
