import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// Mock next/dynamic to render the chart component directly
vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => {
    // Return a mock Chart component that renders props as data attributes
    const MockChart = (props: Record<string, unknown>) => (
      <div
        data-testid="apex-chart"
        data-series={JSON.stringify(props.series)}
        data-options={JSON.stringify(props.options)}
        data-type={props.type as string}
        data-height={props.height as number}
      />
    );
    MockChart.displayName = "MockChart";
    return MockChart;
  },
}));

import { PredictionChart } from "./PredictionChart";
import type { HistoricalPrice, Prediction } from "@/lib/api";

const mockHistoricalData: HistoricalPrice[] = [
  { date: "2024-01-10", open: 2040.0, high: 2055.0, low: 2035.0, close: 2050.0, volume: 100000 },
  { date: "2024-01-11", open: 2050.0, high: 2065.0, low: 2045.0, close: 2060.0, volume: 110000 },
  { date: "2024-01-12", open: 2060.0, high: 2075.0, low: 2055.0, close: 2070.0, volume: 120000 },
];

const mockPredictions: Prediction[] = [
  { predicted_date: "2024-01-13", predicted_close_price: 2080.0, confidence_interval_lower: 2060.0, confidence_interval_upper: 2100.0 },
  { predicted_date: "2024-01-14", predicted_close_price: 2090.0, confidence_interval_lower: 2065.0, confidence_interval_upper: 2115.0 },
  { predicted_date: "2024-01-15", predicted_close_price: 2095.0, confidence_interval_lower: 2070.0, confidence_interval_upper: 2120.0 },
];

describe("PredictionChart", () => {
  it("renders no data message when both historical and predictions are empty", () => {
    render(<PredictionChart historicalData={[]} predictions={[]} />);
    expect(screen.getByText("No data available to display.")).toBeInTheDocument();
  });

  it("renders predictions unavailable message when predictions are empty", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={[]} />);
    expect(
      screen.getByText("Predictions are not yet available. Showing historical data only.")
    ).toBeInTheDocument();
  });

  it("does not show unavailable message when predictions exist", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    expect(
      screen.queryByText("Predictions are not yet available. Showing historical data only.")
    ).not.toBeInTheDocument();
  });

  it("renders the chart component when data is available", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    expect(screen.getByTestId("apex-chart")).toBeInTheDocument();
  });

  it("renders chart with correct type and height", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    const chart = screen.getByTestId("apex-chart");
    expect(chart).toHaveAttribute("data-type", "line");
    expect(chart).toHaveAttribute("data-height", "400");
  });

  it("passes 3 series when predictions are available (historical, predicted, confidence band)", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    const chart = screen.getByTestId("apex-chart");
    const series = JSON.parse(chart.getAttribute("data-series") || "[]");
    expect(series).toHaveLength(3);
    expect(series[0].name).toBe("Historical Close");
    expect(series[1].name).toBe("Predicted Close");
    expect(series[2].name).toBe("95% Confidence Interval");
  });

  it("passes only 1 series when predictions are empty", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={[]} />);
    const chart = screen.getByTestId("apex-chart");
    const series = JSON.parse(chart.getAttribute("data-series") || "[]");
    expect(series).toHaveLength(1);
    expect(series[0].name).toBe("Historical Close");
  });

  it("includes vertical boundary annotation in options when historical data exists", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    const chart = screen.getByTestId("apex-chart");
    const options = JSON.parse(chart.getAttribute("data-options") || "{}");
    expect(options.annotations).toBeDefined();
    expect(options.annotations.xaxis).toHaveLength(1);
    expect(options.annotations.xaxis[0].label.text).toBe("Forecast Start");
  });

  it("sets prediction line as dashed in stroke config", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    const chart = screen.getByTestId("apex-chart");
    const options = JSON.parse(chart.getAttribute("data-options") || "{}");
    // Historical line is solid (0), prediction line is dashed (5)
    expect(options.stroke.dashArray[0]).toBe(0);
    expect(options.stroke.dashArray[1]).toBe(5);
  });

  it("uses different colors for historical and prediction lines", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    const chart = screen.getByTestId("apex-chart");
    const options = JSON.parse(chart.getAttribute("data-options") || "{}");
    // Historical is blue, prediction is amber/orange
    expect(options.colors[0]).not.toBe(options.colors[1]);
  });

  it("renders the heading", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    expect(screen.getByText("Gold Price & Predictions")).toBeInTheDocument();
  });

  it("connects prediction line to last historical point", () => {
    render(<PredictionChart historicalData={mockHistoricalData} predictions={mockPredictions} />);
    const chart = screen.getByTestId("apex-chart");
    const series = JSON.parse(chart.getAttribute("data-series") || "[]");
    const predictionData = series[1].data;
    // First point of prediction series should match last historical close
    const lastHistoricalDate = new Date("2024-01-12").getTime();
    expect(predictionData[0].x).toBe(lastHistoricalDate);
    expect(predictionData[0].y).toBe(2070.0);
  });
});
