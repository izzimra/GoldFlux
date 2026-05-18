"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import type { ApexOptions } from "apexcharts";
import { apiClient, HistoricalPrice } from "@/lib/api";
import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";

// ApexCharts requires client-side rendering; use dynamic import with ssr disabled
const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

type DateRange = "1M" | "3M" | "6M" | "1Y" | "5Y";

const DATE_RANGE_OPTIONS: { label: string; value: DateRange }[] = [
  { label: "1 Month", value: "1M" },
  { label: "3 Months", value: "3M" },
  { label: "6 Months", value: "6M" },
  { label: "1 Year", value: "1Y" },
  { label: "5 Years", value: "5Y" },
];

function getStartDate(range: DateRange): string {
  const now = new Date();
  switch (range) {
    case "1M":
      now.setMonth(now.getMonth() - 1);
      break;
    case "3M":
      now.setMonth(now.getMonth() - 3);
      break;
    case "6M":
      now.setMonth(now.getMonth() - 6);
      break;
    case "1Y":
      now.setFullYear(now.getFullYear() - 1);
      break;
    case "5Y":
      now.setFullYear(now.getFullYear() - 5);
      break;
  }
  return now.toISOString().split("T")[0];
}

function getEndDate(): string {
  return new Date().toISOString().split("T")[0];
}

export interface HistoricalChartProps {
  /** Optional CSS class name for the container */
  className?: string;
}

/**
 * Historical gold price chart component using ApexCharts.
 * Displays close prices with date range selector and detailed tooltips.
 *
 * Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7
 */
export function HistoricalChart({ className }: HistoricalChartProps) {
  const [selectedRange, setSelectedRange] = useState<DateRange>("1M");
  const [data, setData] = useState<HistoricalPrice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (range: DateRange) => {
    setLoading(true);
    setError(null);
    try {
      const startDate = getStartDate(range);
      const endDate = getEndDate();
      const prices = await apiClient.getHistoricalPrices(startDate, endDate);
      setData(prices);
    } catch {
      setError("Failed to load historical price data.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(selectedRange);
  }, [selectedRange, fetchData]);

  const handleRangeChange = (range: DateRange) => {
    setSelectedRange(range);
  };

  const handleRetry = () => {
    fetchData(selectedRange);
  };

  const chartOptions: ApexOptions = useMemo(() => {
    return {
      chart: {
        type: "line",
        height: 400,
        toolbar: { show: true },
        zoom: { enabled: true },
      },
      stroke: {
        curve: "smooth",
        width: 2,
      },
      xaxis: {
        type: "datetime",
        categories: data.map((d) => d.date),
        labels: {
          datetimeUTC: false,
        },
      },
      yaxis: {
        title: { text: "Price (USD)" },
        labels: {
          formatter: (val: number) => `$${val.toFixed(2)}`,
        },
      },
      tooltip: {
        custom: ({ dataPointIndex }: { dataPointIndex: number }) => {
          const point = data[dataPointIndex];
          if (!point) return "";
          return `
            <div class="p-3 bg-white shadow-lg rounded border text-sm">
              <div class="font-semibold mb-1">${point.date}</div>
              <div class="grid grid-cols-2 gap-x-4 gap-y-1">
                <span class="text-gray-500">Open:</span><span>$${point.open.toFixed(2)}</span>
                <span class="text-gray-500">High:</span><span>$${point.high.toFixed(2)}</span>
                <span class="text-gray-500">Low:</span><span>$${point.low.toFixed(2)}</span>
                <span class="text-gray-500">Close:</span><span class="font-medium">$${point.close.toFixed(2)}</span>
                <span class="text-gray-500">Volume:</span><span>${point.volume.toLocaleString()}</span>
              </div>
            </div>
          `;
        },
      },
      colors: ["#f59e0b"],
      grid: {
        borderColor: "#e5e7eb",
      },
      title: {
        text: "Gold Price (GC=F)",
        align: "left",
        style: {
          fontSize: "16px",
          fontWeight: "600",
          color: "#1f2937",
        },
      },
    };
  }, [data]);

  const chartSeries = useMemo(() => {
    return [
      {
        name: "Close Price",
        data: data.map((d) => ({
          x: new Date(d.date).getTime(),
          y: d.close,
        })),
      },
    ];
  }, [data]);

  return (
    <div className={`rounded-lg border border-gray-200 bg-white p-4 ${className || ""}`}>
      {/* Date Range Selector */}
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Date range selector">
        {DATE_RANGE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => handleRangeChange(option.value)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              selectedRange === option.value
                ? "bg-amber-500 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
            aria-pressed={selectedRange === option.value}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* Loading State */}
      {loading && <LoadingSkeleton lines={8} className="h-[400px]" />}

      {/* Error State */}
      {!loading && error && <ErrorState message={error} onRetry={handleRetry} variant="generic" />}

      {/* Empty State */}
      {!loading && !error && data.length === 0 && (
        <div className="flex h-[400px] items-center justify-center text-gray-500">
          <p>No data available for the selected range.</p>
        </div>
      )}

      {/* Chart */}
      {!loading && !error && data.length > 0 && (
        <Chart
          options={chartOptions}
          series={chartSeries}
          type="line"
          height={400}
        />
      )}
    </div>
  );
}
