import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MarketInsightsPanel } from "../MarketInsightsPanel";
import { ServiceUnavailableError } from "../../lib/api";
import type { NewsResponse } from "../../lib/api";

// Mock the API client
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual("../../lib/api");
  return {
    ...actual,
    apiClient: {
      getNews: vi.fn(),
    },
  };
});

import { apiClient } from "../../lib/api";

const mockGetNews = apiClient.getNews as ReturnType<typeof vi.fn>;

function createMockArticle(overrides: Partial<{ title: string; published_at: string }> = {}) {
  return {
    title: overrides.title || "Gold Prices Rise",
    source_name: "Reuters",
    source_url: "https://reuters.com/article/1",
    published_at: overrides.published_at || "2024-01-15T12:00:00Z",
    description: "Gold futures climbed to a three-week high.",
    sentiment_score: 0.65,
    sentiment_label: "positive",
  };
}

function createMockResponse(articleCount: number = 5): NewsResponse {
  const articles = Array.from({ length: articleCount }, (_, i) => {
    const date = new Date("2024-01-15T12:00:00Z");
    date.setHours(date.getHours() - i);
    return createMockArticle({
      title: `Article ${i + 1}`,
      published_at: date.toISOString(),
    });
  });

  return {
    last_updated: "2024-01-15T14:30:00Z",
    articles,
  };
}

describe("MarketInsightsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading skeleton while fetching", () => {
    mockGetNews.mockReturnValue(new Promise(() => {})); // never resolves
    render(<MarketInsightsPanel />);
    expect(screen.getByText("Market Insights")).toBeInTheDocument();
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("displays articles after successful fetch", async () => {
    mockGetNews.mockResolvedValue(createMockResponse(3));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });
    expect(screen.getByText("Article 2")).toBeInTheDocument();
    expect(screen.getByText("Article 3")).toBeInTheDocument();
  });

  it("shows 'No news available' for empty response", async () => {
    mockGetNews.mockResolvedValue({ last_updated: "2024-01-15T14:30:00Z", articles: [] });
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/no news.*available/i)).toBeInTheDocument();
    });
  });

  it("shows error state with retry on fetch failure", async () => {
    mockGetNews.mockRejectedValue(new ServiceUnavailableError());
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Retry")).toBeInTheDocument();
  });

  it("shows timeout variant for TypeError (network error)", async () => {
    mockGetNews.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
  });

  it("retries fetch when retry button is clicked", async () => {
    mockGetNews.mockRejectedValueOnce(new Error("fail"));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByLabelText("Retry")).toBeInTheDocument();
    });

    mockGetNews.mockResolvedValue(createMockResponse(2));
    fireEvent.click(screen.getByLabelText("Retry"));

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });
  });

  it("shows max 10 articles by default with Show More button", async () => {
    mockGetNews.mockResolvedValue(createMockResponse(15));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    // Should show 10 articles
    expect(screen.getByText("Article 10")).toBeInTheDocument();
    expect(screen.queryByText("Article 11")).not.toBeInTheDocument();

    // Show More button should be visible
    expect(screen.getByText("Show More")).toBeInTheDocument();
  });

  it("shows all articles when Show More is clicked", async () => {
    mockGetNews.mockResolvedValue(createMockResponse(15));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Show More")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Show More"));

    expect(screen.getByText("Article 11")).toBeInTheDocument();
    expect(screen.getByText("Article 15")).toBeInTheDocument();
    // Show More should disappear since all articles are shown
    expect(screen.queryByText("Show More")).not.toBeInTheDocument();
  });

  it("does not show Show More button when articles <= 10", async () => {
    mockGetNews.mockResolvedValue(createMockResponse(8));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    expect(screen.queryByText("Show More")).not.toBeInTheDocument();
  });

  it("orders articles by published_at descending", async () => {
    const response: NewsResponse = {
      last_updated: "2024-01-15T14:30:00Z",
      articles: [
        createMockArticle({ title: "Older", published_at: "2024-01-10T12:00:00Z" }),
        createMockArticle({ title: "Newest", published_at: "2024-01-15T12:00:00Z" }),
        createMockArticle({ title: "Middle", published_at: "2024-01-12T12:00:00Z" }),
      ],
    };
    mockGetNews.mockResolvedValue(response);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Newest")).toBeInTheDocument();
    });

    const articles = screen.getAllByRole("article");
    expect(articles[0]).toHaveTextContent("Newest");
    expect(articles[1]).toHaveTextContent("Middle");
    expect(articles[2]).toHaveTextContent("Older");
  });

  it("calls getNews with limit 30", async () => {
    mockGetNews.mockResolvedValue(createMockResponse(1));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(mockGetNews).toHaveBeenCalledWith(30);
    });
  });

  it("refreshes news when refresh button is clicked", async () => {
    mockGetNews.mockResolvedValue(createMockResponse(2));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    mockGetNews.mockResolvedValue(
      createMockResponse(1)
    );

    fireEvent.click(screen.getByLabelText("Refresh news"));

    await waitFor(() => {
      expect(mockGetNews).toHaveBeenCalledTimes(2);
    });
  });
});
