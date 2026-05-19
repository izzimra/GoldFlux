import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { ErrorNotification } from "./ErrorNotification";
import type { FetchError } from "../lib/useDataFetching";

describe("ErrorNotification", () => {
  const genericError: FetchError = {
    type: "generic",
    message: "Something went wrong. Please try again.",
  };

  const timeoutError: FetchError = {
    type: "timeout",
    message: "The request timed out. Please check your connection and try again.",
  };

  it("renders the error message", () => {
    render(<ErrorNotification error={genericError} />);
    expect(screen.getByText(genericError.message)).toBeInTheDocument();
  });

  it("renders retry button when onRetry is provided", () => {
    const onRetry = vi.fn();
    render(<ErrorNotification error={genericError} onRetry={onRetry} />);

    const retryButton = screen.getByRole("button", { name: /retry/i });
    expect(retryButton).toBeInTheDocument();

    fireEvent.click(retryButton);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders dismiss button when onDismiss is provided", () => {
    const onDismiss = vi.fn();
    render(<ErrorNotification error={genericError} onDismiss={onDismiss} />);

    const dismissButton = screen.getByRole("button", { name: /dismiss/i });
    expect(dismissButton).toBeInTheDocument();

    fireEvent.click(dismissButton);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("shows persistent failure message when isPersistent is true", () => {
    render(<ErrorNotification error={genericError} isPersistent={true} />);

    expect(
      screen.getByText(/unable to refresh data after multiple attempts/i)
    ).toBeInTheDocument();
  });

  it("does not show retry button when isPersistent is true", () => {
    const onRetry = vi.fn();
    render(
      <ErrorNotification error={genericError} isPersistent={true} onRetry={onRetry} />
    );

    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("has role=alert for accessibility", () => {
    render(<ErrorNotification error={timeoutError} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
