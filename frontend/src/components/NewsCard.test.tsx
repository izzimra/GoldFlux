import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import React from "react";
import { NewsCard, getRelativeTime } from "./NewsCard";
import type { NewsArticle } from "../lib/api";

const mockArticle: NewsArticle = {
  title: "Gold Prices Surge Amid Fed Rate Decision Uncertainty",
  source_name: "Reuters",
  source_url: "https://reuters.com/article/gold-surge",
  published_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
  description:
    "Gold futures climbed to a three-week high as investors weighed the Federal Reserve's upcoming rate decision. Analysts expect continued volatility in precious metals markets through the end of the quarter as economic data remains mixed.",
  sentiment_score: 0.65,
  sentiment_label: "positive",
};

describe("NewsCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-06-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the article title as a clickable link", () => {
    render(<NewsCard article={mockArticle} />);
    const link = screen.getByRole("link");
    expect(link).toHaveTextContent(mockArticle.title);
    expect(link).toHaveAttribute("href", mockArticle.source_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows full title in tooltip on hover via title attribute", () => {
    render(<NewsCard article={mockArticle} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("title", mockArticle.title);
  });

  it("applies line-clamp-2 class for title truncation", () => {
    render(<NewsCard article={mockArticle} />);
    const link = screen.getByRole("link");
    expect(link).toHaveClass("line-clamp-2");
  });

  it("displays the source name", () => {
    render(<NewsCard article={mockArticle} />);
    expect(screen.getByText("Reuters")).toBeInTheDocument();
  });

  it("displays relative publication time", () => {
    const twoHoursAgo = new Date("2024-06-15T10:00:00Z").toISOString();
    const article = { ...mockArticle, published_at: twoHoursAgo };
    render(<NewsCard article={article} />);
    expect(screen.getByText("2 hours ago")).toBeInTheDocument();
  });

  it("renders the SentimentBadge with correct label", () => {
    render(<NewsCard article={mockArticle} />);
    expect(screen.getByText("Positive")).toBeInTheDocument();
  });

  it("truncates description to 100 chars with ellipsis by default", () => {
    render(<NewsCard article={mockArticle} />);
    // The description is longer than 100 chars, so it should be truncated
    const truncated = mockArticle.description.slice(0, 100).trimEnd() + "…";
    expect(screen.getByText(truncated, { exact: false })).toBeInTheDocument();
    // Full description should not be visible
    expect(screen.queryByText(mockArticle.description)).not.toBeInTheDocument();
  });

  it("shows 'Read more' button when description exceeds 100 chars", () => {
    render(<NewsCard article={mockArticle} />);
    expect(screen.getByText("Read more")).toBeInTheDocument();
  });

  it("expands description to full text on 'Read more' click", () => {
    render(<NewsCard article={mockArticle} />);
    fireEvent.click(screen.getByText("Read more"));
    expect(screen.getByText(mockArticle.description, { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Show less")).toBeInTheDocument();
  });

  it("collapses description back on 'Show less' click", () => {
    render(<NewsCard article={mockArticle} />);
    fireEvent.click(screen.getByText("Read more"));
    fireEvent.click(screen.getByText("Show less"));
    expect(screen.queryByText(mockArticle.description)).not.toBeInTheDocument();
    expect(screen.getByText("Read more")).toBeInTheDocument();
  });

  it("does not show expand button when description is 100 chars or less", () => {
    const shortArticle = { ...mockArticle, description: "Short description." };
    render(<NewsCard article={shortArticle} />);
    expect(screen.queryByText("Read more")).not.toBeInTheDocument();
    expect(screen.getByText("Short description.")).toBeInTheDocument();
  });

  it("handles empty description gracefully", () => {
    const noDescArticle = { ...mockArticle, description: "" };
    render(<NewsCard article={noDescArticle} />);
    expect(screen.queryByText("Read more")).not.toBeInTheDocument();
  });
});

describe("getRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2024-06-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'just now' for timestamps less than a minute ago", () => {
    const now = new Date("2024-06-15T11:59:30Z").toISOString();
    expect(getRelativeTime(now)).toBe("just now");
  });

  it("returns minutes ago for timestamps within the hour", () => {
    const thirtyMinAgo = new Date("2024-06-15T11:30:00Z").toISOString();
    expect(getRelativeTime(thirtyMinAgo)).toBe("30 minutes ago");
  });

  it("returns '1 minute ago' for singular", () => {
    const oneMinAgo = new Date("2024-06-15T11:59:00Z").toISOString();
    expect(getRelativeTime(oneMinAgo)).toBe("1 minute ago");
  });

  it("returns hours ago for timestamps within the day", () => {
    const fiveHoursAgo = new Date("2024-06-15T07:00:00Z").toISOString();
    expect(getRelativeTime(fiveHoursAgo)).toBe("5 hours ago");
  });

  it("returns '1 hour ago' for singular", () => {
    const oneHourAgo = new Date("2024-06-15T11:00:00Z").toISOString();
    expect(getRelativeTime(oneHourAgo)).toBe("1 hour ago");
  });

  it("returns days ago for timestamps within the week", () => {
    const threeDaysAgo = new Date("2024-06-12T12:00:00Z").toISOString();
    expect(getRelativeTime(threeDaysAgo)).toBe("3 days ago");
  });

  it("returns '1 day ago' for singular", () => {
    const oneDayAgo = new Date("2024-06-14T12:00:00Z").toISOString();
    expect(getRelativeTime(oneDayAgo)).toBe("1 day ago");
  });

  it("returns weeks ago for timestamps within the month", () => {
    const twoWeeksAgo = new Date("2024-06-01T12:00:00Z").toISOString();
    expect(getRelativeTime(twoWeeksAgo)).toBe("2 weeks ago");
  });

  it("returns months ago for timestamps within the year", () => {
    const threeMonthsAgo = new Date("2024-03-15T12:00:00Z").toISOString();
    expect(getRelativeTime(threeMonthsAgo)).toBe("3 months ago");
  });

  it("returns years ago for old timestamps", () => {
    const twoYearsAgo = new Date("2022-06-15T12:00:00Z").toISOString();
    expect(getRelativeTime(twoYearsAgo)).toBe("2 years ago");
  });

  it("returns 'just now' for future timestamps", () => {
    const future = new Date("2024-06-16T12:00:00Z").toISOString();
    expect(getRelativeTime(future)).toBe("just now");
  });
});
