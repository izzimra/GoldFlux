import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { ErrorState } from "./ErrorState";

describe("ErrorState", () => {
  it("renders generic error message by default", () => {
    render(<ErrorState />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText("Something went wrong. Please try again.")
    ).toBeInTheDocument();
  });

  it("renders timeout variant message", () => {
    render(<ErrorState variant="timeout" />);
    expect(
      screen.getByText(
        "The request timed out. Please check your connection and try again."
      )
    ).toBeInTheDocument();
  });

  it("renders unavailable variant message", () => {
    render(<ErrorState variant="unavailable" />);
    expect(
      screen.getByText(
        "The service is temporarily unavailable. Please try again later."
      )
    ).toBeInTheDocument();
  });

  it("renders custom message when provided", () => {
    render(<ErrorState message="Custom error occurred" />);
    expect(screen.getByText("Custom error occurred")).toBeInTheDocument();
  });

  it("renders retry button when onRetry is provided", () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} />);
    const button = screen.getByRole("button", { name: /retry/i });
    expect(button).toBeInTheDocument();
  });

  it("does not render retry button when onRetry is not provided", () => {
    render(<ErrorState />);
    expect(
      screen.queryByRole("button", { name: /retry/i })
    ).not.toBeInTheDocument();
  });

  it("calls onRetry when retry button is clicked", () => {
    const onRetry = vi.fn();
    render(<ErrorState onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("has proper ARIA attributes for accessibility", () => {
    render(<ErrorState />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
  });

  it("custom message overrides variant default", () => {
    render(<ErrorState variant="timeout" message="Override message" />);
    expect(screen.getByText("Override message")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "The request timed out. Please check your connection and try again."
      )
    ).not.toBeInTheDocument();
  });
});
