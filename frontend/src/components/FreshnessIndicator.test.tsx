import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import {
  FreshnessIndicator,
  formatRelativeTime,
  isStale,
} from "./FreshnessIndicator";

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-01-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns "just now" for timestamps less than 60 seconds ago', () => {
    expect(formatRelativeTime("2024-01-15T11:59:30Z")).toBe("just now");
  });

  it('returns "1 minute ago" for exactly 1 minute', () => {
    expect(formatRelativeTime("2024-01-15T11:59:00Z")).toBe("1 minute ago");
  });

  it("returns minutes ago for timestamps within the last hour", () => {
    expect(formatRelativeTime("2024-01-15T11:45:00Z")).toBe("15 minutes ago");
  });

  it('returns "1 hour ago" for exactly 1 hour', () => {
    expect(formatRelativeTime("2024-01-15T11:00:00Z")).toBe("1 hour ago");
  });

  it("returns hours ago for timestamps within the last day", () => {
    expect(formatRelativeTime("2024-01-15T10:00:00Z")).toBe("2 hours ago");
  });

  it('returns "1 day ago" for exactly 1 day', () => {
    expect(formatRelativeTime("2024-01-14T12:00:00Z")).toBe("1 day ago");
  });

  it("returns days ago for older timestamps", () => {
    expect(formatRelativeTime("2024-01-12T12:00:00Z")).toBe("3 days ago");
  });

  it('returns "just now" for future timestamps', () => {
    expect(formatRelativeTime("2024-01-15T13:00:00Z")).toBe("just now");
  });
});

describe("isStale", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-01-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns false for timestamps less than 6 hours old", () => {
    expect(isStale("2024-01-15T07:00:00Z")).toBe(false);
  });

  it("returns false for timestamps exactly 6 hours old", () => {
    expect(isStale("2024-01-15T06:00:00Z")).toBe(false);
  });

  it("returns true for timestamps older than 6 hours", () => {
    expect(isStale("2024-01-15T05:59:59Z")).toBe(true);
  });
});

describe("FreshnessIndicator", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-01-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("displays relative time when lastUpdated is provided", () => {
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T11:45:00Z"
        onRefresh={() => {}}
        isRefreshing={false}
      />
    );
    expect(screen.getByText("Updated 15 minutes ago")).toBeInTheDocument();
  });

  it('displays "No update info available" when lastUpdated is null', () => {
    render(
      <FreshnessIndicator
        lastUpdated={null}
        onRefresh={() => {}}
        isRefreshing={false}
      />
    );
    expect(screen.getByText("No update info available")).toBeInTheDocument();
  });

  it("shows amber warning icon when data is stale (>6 hours)", () => {
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T05:00:00Z"
        onRefresh={() => {}}
        isRefreshing={false}
      />
    );
    const warningIcon = screen.getByLabelText("Stale data warning");
    expect(warningIcon).toBeInTheDocument();
    expect(warningIcon).toHaveClass("text-amber-500");
  });

  it("does not show warning icon when data is fresh", () => {
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T11:00:00Z"
        onRefresh={() => {}}
        isRefreshing={false}
      />
    );
    expect(screen.queryByLabelText("Stale data warning")).not.toBeInTheDocument();
  });

  it("calls onRefresh when refresh button is clicked", () => {
    const onRefresh = vi.fn();
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T11:45:00Z"
        onRefresh={onRefresh}
        isRefreshing={false}
      />
    );
    fireEvent.click(screen.getByLabelText("Refresh news"));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("disables refresh button when isRefreshing is true", () => {
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T11:45:00Z"
        onRefresh={() => {}}
        isRefreshing={true}
      />
    );
    const button = screen.getByLabelText("Refresh news");
    expect(button).toBeDisabled();
    expect(button).toHaveClass("opacity-50");
  });

  it("shows spinning animation on refresh icon when isRefreshing is true", () => {
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T11:45:00Z"
        onRefresh={() => {}}
        isRefreshing={true}
      />
    );
    const button = screen.getByLabelText("Refresh news");
    const svg = button.querySelector("svg");
    expect(svg).toHaveClass("animate-spin");
  });

  it("does not show spinning animation when not refreshing", () => {
    render(
      <FreshnessIndicator
        lastUpdated="2024-01-15T11:45:00Z"
        onRefresh={() => {}}
        isRefreshing={false}
      />
    );
    const button = screen.getByLabelText("Refresh news");
    const svg = button.querySelector("svg");
    expect(svg).not.toHaveClass("animate-spin");
  });
});
