import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { LoadingSkeleton } from "./LoadingSkeleton";

describe("LoadingSkeleton", () => {
  it("renders 3 skeleton lines by default", () => {
    const { container } = render(<LoadingSkeleton />);
    const lines = container.querySelectorAll(".h-4.rounded.bg-gray-200");
    expect(lines).toHaveLength(3);
  });

  it("renders the specified number of lines", () => {
    const { container } = render(<LoadingSkeleton lines={5} />);
    const lines = container.querySelectorAll(".h-4.rounded.bg-gray-200");
    expect(lines).toHaveLength(5);
  });

  it("renders 1 line when lines=1", () => {
    const { container } = render(<LoadingSkeleton lines={1} />);
    const lines = container.querySelectorAll(".h-4.rounded.bg-gray-200");
    expect(lines).toHaveLength(1);
  });

  it("applies custom className to container", () => {
    const { container } = render(<LoadingSkeleton className="mt-4" />);
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("mt-4");
  });

  it("has proper ARIA attributes for accessibility", () => {
    render(<LoadingSkeleton />);
    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-label", "Loading content");
    expect(status).toHaveAttribute("aria-busy", "true");
  });

  it("includes screen reader text", () => {
    render(<LoadingSkeleton />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("last line is shorter (w-3/4) for visual variety", () => {
    const { container } = render(<LoadingSkeleton lines={3} />);
    const lines = container.querySelectorAll(".h-4.rounded.bg-gray-200");
    const lastLine = lines[lines.length - 1];
    expect(lastLine.className).toContain("w-3/4");
  });

  it("non-last lines are full width", () => {
    const { container } = render(<LoadingSkeleton lines={3} />);
    const lines = container.querySelectorAll(".h-4.rounded.bg-gray-200");
    expect(lines[0].className).toContain("w-full");
    expect(lines[1].className).toContain("w-full");
  });

  it("has animate-pulse class for animation", () => {
    const { container } = render(<LoadingSkeleton />);
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("animate-pulse");
  });
});
