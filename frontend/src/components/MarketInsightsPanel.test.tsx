import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { MarketInsightsPanel, DashboardLayout } from "./MarketInsightsPanel";

// Mock the api module
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return {
    ...actual,
    apiClient: {
      getNews: vi.fn(),
    },
  };
});

import { apiClient } from "@/lib/api";

const mockGetNews = vi.mocked(apiClient.getNews);

function makeArticle(index: number) {
  const date = new Date(Date.now() - index * 3600000); // each article 1 hour apart
  return {
    title: `Article ${index + 1}`,
    source_name: `Source ${index + 1}`,
    source_url: `https://example.com/article-${index + 1}`,
    published_at: date.toISOString(),
    description: `Description for article ${index + 1}. This is some sample text.`,
    sentiment_score: index % 3 === 0 ? 0.5 : index % 3 === 1 ? -0.5 : 0.0,
    sentiment_label: index % 3 === 0 ? "positive" : index % 3 === 1 ? "negative" : "neutral",
  };
}

function makeArticles(count: number) {
  return Array.from({ length: count }, (_, i) => makeArticle(i));
}

const mockNewsResponse = {
  last_updated: new Date(Date.now() - 900000).toISOString(), // 15 minutes ago
  articles: makeArticles(15),
};

describe("MarketInsightsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading skeleton while fetching", () => {
    mockGetNews.mockReturnValue(new Promise(() => {})); // never resolves
    render(<MarketInsightsPanel />);
    expect(screen.getByText("Market Insights")).toBeInTheDocument();
    // Multiple LoadingSkeleton instances are rendered
    const skeletons = screen.getAllByRole("status");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("displays articles on successful fetch", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    expect(screen.getByText("Article 10")).toBeInTheDocument();
  });

  it("shows max 10 articles by default", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    // Article 11 should not be visible (only 10 shown by default)
    expect(screen.queryByText("Article 11")).not.toBeInTheDocument();
  });

  it("shows 'Show More' button when more than 10 articles available", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Show More")).toBeInTheDocument();
    });
  });

  it("loads remaining articles when 'Show More' is clicked", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Show More")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Show More"));

    expect(screen.getByText("Article 11")).toBeInTheDocument();
    expect(screen.getByText("Article 15")).toBeInTheDocument();
    // Show More button should disappear since all articles are now visible
    expect(screen.queryByText("Show More")).not.toBeInTheDocument();
  });

  it("does not show 'Show More' when 10 or fewer articles", async () => {
    mockGetNews.mockResolvedValue({
      last_updated: new Date().toISOString(),
      articles: makeArticles(8),
    });
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    expect(screen.queryByText("Show More")).not.toBeInTheDocument();
  });

  it("shows 'no news available' message for empty response", async () => {
    mockGetNews.mockResolvedValue({
      last_updated: new Date().toISOString(),
      articles: [],
    });
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("No news is currently available.")).toBeInTheDocument();
    });
  });

  it("shows error state with retry button on failure", async () => {
    mockGetNews.mockRejectedValue(new Error("Network error"));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Something went wrong. Please try again.")).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("retries fetch when retry button is clicked", async () => {
    mockGetNews.mockRejectedValueOnce(new Error("Network error"));
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Something went wrong. Please try again.")).toBeInTheDocument();
    });

    mockGetNews.mockResolvedValueOnce(mockNewsResponse);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });
  });

  it("displays FreshnessIndicator at top", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByLabelText("Refresh news")).toBeInTheDocument();
    });
  });

  it("refreshes data when refresh button is clicked", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(screen.getByText("Article 1")).toBeInTheDocument();
    });

    const updatedResponse = {
      last_updated: new Date().toISOString(),
      articles: [makeArticle(0)],
    };
    mockGetNews.mockResolvedValueOnce(updatedResponse);
    fireEvent.click(screen.getByLabelText("Refresh news"));

    await waitFor(() => {
      // After refresh with only 1 article, Article 2 should be gone
      expect(screen.queryByText("Article 2")).not.toBeInTheDocument();
    });
  });

  it("fetches news with limit of 30", async () => {
    mockGetNews.mockResolvedValue(mockNewsResponse);
    render(<MarketInsightsPanel />);

    await waitFor(() => {
      expect(mockGetNews).toHaveBeenCalledWith(30);
    });
  });

  describe("responsive layout (Requirements 21.1, 21.2, 21.3)", () => {
    it("renders as aside element with responsive Tailwind classes", async () => {
      mockGetNews.mockResolvedValue(mockNewsResponse);
      render(<MarketInsightsPanel />);

      await waitFor(() => {
        expect(screen.getByText("Article 1")).toBeInTheDocument();
      });

      const panel = screen.getByLabelText("Market Insights");
      expect(panel.tagName).toBe("ASIDE");
      // Desktop: max 30% viewport width
      expect(panel.className).toContain("lg:max-w-[30vw]");
      // Mobile: full width
      expect(panel.className).toContain("w-full");
    });

    it("applies desktop sidebar classes (sticky, self-start)", async () => {
      mockGetNews.mockResolvedValue(mockNewsResponse);
      render(<MarketInsightsPanel />);

      await waitFor(() => {
        expect(screen.getByText("Article 1")).toBeInTheDocument();
      });

      const panel = screen.getByLabelText("Market Insights");
      expect(panel.className).toContain("lg:sticky");
      expect(panel.className).toContain("lg:self-start");
    });

    it("applies responsive classes in loading state", () => {
      mockGetNews.mockReturnValue(new Promise(() => {}));
      render(<MarketInsightsPanel />);

      const panel = screen.getByLabelText("Market Insights");
      expect(panel.className).toContain("lg:max-w-[30vw]");
      expect(panel.className).toContain("w-full");
    });

    it("applies responsive classes in error state", async () => {
      mockGetNews.mockRejectedValue(new Error("fail"));
      render(<MarketInsightsPanel />);

      await waitFor(() => {
        expect(screen.getByRole("alert")).toBeInTheDocument();
      });

      const panel = screen.getByLabelText("Market Insights");
      expect(panel.className).toContain("lg:max-w-[30vw]");
      expect(panel.className).toContain("w-full");
    });
  });

  describe("DashboardLayout", () => {
    it("renders flex-col on mobile and flex-row on desktop", async () => {
      mockGetNews.mockResolvedValue(mockNewsResponse);
      const { container } = render(
        <DashboardLayout>
          <div data-testid="chart-area">Chart</div>
        </DashboardLayout>
      );

      await waitFor(() => {
        expect(screen.getByText("Article 1")).toBeInTheDocument();
      });

      const layout = container.firstElementChild as HTMLElement;
      expect(layout.className).toContain("flex-col");
      expect(layout.className).toContain("lg:flex-row");
    });

    it("renders main content area with flex-1", async () => {
      mockGetNews.mockResolvedValue(mockNewsResponse);
      render(
        <DashboardLayout>
          <div data-testid="chart-area">Chart</div>
        </DashboardLayout>
      );

      await waitFor(() => {
        expect(screen.getByText("Article 1")).toBeInTheDocument();
      });

      const main = screen.getByRole("main");
      expect(main.className).toContain("flex-1");
      expect(main.className).toContain("min-w-0");
    });

    it("renders MarketInsightsPanel as sidebar within layout", async () => {
      mockGetNews.mockResolvedValue(mockNewsResponse);
      render(
        <DashboardLayout>
          <div>Chart</div>
        </DashboardLayout>
      );

      await waitFor(() => {
        expect(screen.getByLabelText("Market Insights")).toBeInTheDocument();
      });
    });
  });
});
