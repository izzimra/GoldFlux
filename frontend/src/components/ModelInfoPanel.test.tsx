import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { ModelInfoPanel } from "./ModelInfoPanel";
import { APIError } from "@/lib/api";

// Mock the api module
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return {
    ...actual,
    apiClient: {
      getModelMetadata: vi.fn(),
    },
  };
});

import { apiClient } from "@/lib/api";

const mockGetModelMetadata = vi.mocked(apiClient.getModelMetadata);

const mockMetadata = {
  training_date: "2024-01-15T02:30:00Z",
  mean_absolute_error: 12.4567,
  root_mean_squared_error: 18.7234,
  number_of_training_samples: 1257,
  model_version: "v2024-01-15",
};

describe("ModelInfoPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading skeleton while fetching", () => {
    mockGetModelMetadata.mockReturnValue(new Promise(() => {})); // never resolves
    render(<ModelInfoPanel />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Model Information")).toBeInTheDocument();
  });

  it("displays model metadata on successful fetch", async () => {
    mockGetModelMetadata.mockResolvedValue(mockMetadata);
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(screen.getByText("v2024-01-15")).toBeInTheDocument();
    });

    expect(screen.getByText("12.46")).toBeInTheDocument();
    expect(screen.getByText("18.72")).toBeInTheDocument();
    expect(screen.getByText("Model Information")).toBeInTheDocument();
  });

  it("displays MAE rounded to 2 decimal places", async () => {
    mockGetModelMetadata.mockResolvedValue(mockMetadata);
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(screen.getByText("12.46")).toBeInTheDocument();
    });
  });

  it("displays RMSE rounded to 2 decimal places", async () => {
    mockGetModelMetadata.mockResolvedValue(mockMetadata);
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(screen.getByText("18.72")).toBeInTheDocument();
    });
  });

  it("shows 'no model trained' message on 404 response", async () => {
    mockGetModelMetadata.mockRejectedValue(new APIError(404, { message: "Not found" }));
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(
        screen.getByText("No model has been trained yet.")
      ).toBeInTheDocument();
    });
  });

  it("shows error state with retry on fetch failure", async () => {
    mockGetModelMetadata.mockRejectedValue(new Error("Network error"));
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(
        screen.getByText("Model information could not be loaded.")
      ).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("retries fetch when retry button is clicked in error state", async () => {
    mockGetModelMetadata.mockRejectedValueOnce(new Error("Network error"));
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(
        screen.getByText("Model information could not be loaded.")
      ).toBeInTheDocument();
    });

    mockGetModelMetadata.mockResolvedValueOnce(mockMetadata);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText("v2024-01-15")).toBeInTheDocument();
    });
  });

  it("supports manual refresh via refresh button", async () => {
    mockGetModelMetadata.mockResolvedValue(mockMetadata);
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(screen.getByText("v2024-01-15")).toBeInTheDocument();
    });

    const refreshButton = screen.getByRole("button", {
      name: /refresh model information/i,
    });
    expect(refreshButton).toBeInTheDocument();

    const updatedMetadata = { ...mockMetadata, model_version: "v2024-02-01" };
    mockGetModelMetadata.mockResolvedValueOnce(updatedMetadata);
    fireEvent.click(refreshButton);

    await waitFor(() => {
      expect(screen.getByText("v2024-02-01")).toBeInTheDocument();
    });
  });

  it("shows refresh button in no_model state", async () => {
    mockGetModelMetadata.mockRejectedValue(new APIError(404, { message: "Not found" }));
    render(<ModelInfoPanel />);

    await waitFor(() => {
      expect(
        screen.getByText("No model has been trained yet.")
      ).toBeInTheDocument();
    });

    expect(
      screen.getByRole("button", { name: /refresh model information/i })
    ).toBeInTheDocument();
  });
});
