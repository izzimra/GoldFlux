import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { HistoricalChart } from "./HistoricalChart";

// Mock next/dynamic to render the chart component directly
vi.mock("next/dynamic", () => ({
  __esModule: true,
  default: () => {
    const MockChart = (props: { options: unknown; series: unknown }) => (
      <div data-testid="apex-chart" data-options={JSON.stringify(props.options)} data-series={JSON.stringify(props.series)}>
        ApexChart
      </div>
    );
    MockChart.displayName = "MockChart";
    return MockChart;
  },
}));

const mockPrices = [
  { date: "2024-01-10", open: 2040.0, high: 2055.0, low: 2035.0, close: 2050.0, volume: 150000 },
  { date: "2024-01-11", open: 2050.0, high: 2065.0, low: 2045.0, close: 2060.0, volume: 160000 },
  { date: "2024-01-12", open: 2060.0, high: 2070.0, low: 2050.0, close: 2055.0, volume: 140000 },
];

// Mock the api module
const mockGetHistoricalPrices = vi.fn();
vi.mock("@/lib/api", () => ({
  apiClient: {
    getHistoricalPrices: (...args: unknown[]) => mockGetHistoricalPrices(...args),
  },
}));

describe("HistoricalChart", () => {
  beforeEach(() => {
    mockGetHistoricalPrices.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading skeleton while fetching data", () => {
    mockGetHistoricalPrices.mockReturnValue(new Promise(() => {})); // never resolves
    render(<HistoricalChart />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders chart after successful data fetch", async () => {
    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    render(<HistoricalChart />);

    await waitFor(() => {
      expect(screen.getByTestId("apex-chart")).toBeInTheDocument();
    });
  });

  it("shows error state with retry on fetch failure", async () => {
    mockGetHistoricalPrices.mockRejectedValue(new Error("Network error"));
    render(<HistoricalChart />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByText("Failed to load historical price data.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows no data message for empty response", async () => {
    mockGetHistoricalPrices.mockResolvedValue([]);
    render(<HistoricalChart />);

    await waitFor(() => {
      expect(screen.getByText("No data available for the selected range.")).toBeInTheDocument();
    });
  });

  it("renders date range selector buttons", async () => {
    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    render(<HistoricalChart />);

    expect(screen.getByText("1 Month")).toBeInTheDocument();
    expect(screen.getByText("3 Months")).toBeInTheDocument();
    expect(screen.getByText("6 Months")).toBeInTheDocument();
    expect(screen.getByText("1 Year")).toBeInTheDocument();
    expect(screen.getByText("5 Years")).toBeInTheDocument();
  });

  it("defaults to 1 month range", async () => {
    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    render(<HistoricalChart />);

    const oneMonthBtn = screen.getByText("1 Month");
    expect(oneMonthBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("fetches new data when range is changed", async () => {
    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    render(<HistoricalChart />);

    await waitFor(() => {
      expect(screen.getByTestId("apex-chart")).toBeInTheDocument();
    });

    // Change to 1 Year
    fireEvent.click(screen.getByText("1 Year"));

    await waitFor(() => {
      expect(mockGetHistoricalPrices).toHaveBeenCalledTimes(2);
    });
  });

  it("retries fetch when retry button is clicked", async () => {
    mockGetHistoricalPrices.mockRejectedValueOnce(new Error("Network error"));
    render(<HistoricalChart />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByTestId("apex-chart")).toBeInTheDocument();
    });
  });

  it("passes correct date parameters to API", async () => {
    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    render(<HistoricalChart />);

    await waitFor(() => {
      expect(mockGetHistoricalPrices).toHaveBeenCalledTimes(1);
    });

    const [startDate, endDate] = mockGetHistoricalPrices.mock.calls[0];
    // Verify dates are in YYYY-MM-DD format
    expect(startDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(endDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("applies custom className", () => {
    mockGetHistoricalPrices.mockResolvedValue(mockPrices);
    const { container } = render(<HistoricalChart className="custom-class" />);
    expect(container.firstChild).toHaveClass("custom-class");
  });
});
