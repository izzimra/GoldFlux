import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { SentimentBadge } from "./SentimentBadge";

describe("SentimentBadge", () => {
  it("renders positive sentiment with green styling", () => {
    render(<SentimentBadge sentimentLabel="positive" />);
    const badge = screen.getByText("Positive");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("bg-green-100", "text-green-800");
  });

  it("renders neutral sentiment with gray styling", () => {
    render(<SentimentBadge sentimentLabel="neutral" />);
    const badge = screen.getByText("Neutral");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("bg-gray-100", "text-gray-800");
  });

  it("renders negative sentiment with red styling", () => {
    render(<SentimentBadge sentimentLabel="negative" />);
    const badge = screen.getByText("Negative");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("bg-red-100", "text-red-800");
  });

  it("renders with rounded badge styling", () => {
    render(<SentimentBadge sentimentLabel="positive" />);
    const badge = screen.getByText("Positive");
    expect(badge).toHaveClass("px-2", "py-0.5", "rounded-full", "text-xs", "font-medium");
  });

  it("capitalizes the label text", () => {
    render(<SentimentBadge sentimentLabel="negative" />);
    expect(screen.getByText("Negative")).toBeInTheDocument();
    expect(screen.queryByText("negative")).not.toBeInTheDocument();
  });
});
