import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MetricCard } from "@/components/MetricCard";

describe("MetricCard", () => {
  it("renders label, value and sub-text", () => {
    render(<MetricCard label="Accuracy" value="91%" sub="pass rate" />);
    expect(screen.getByText("Accuracy")).toBeInTheDocument();
    expect(screen.getByText("91%")).toBeInTheDocument();
    expect(screen.getByText("pass rate")).toBeInTheDocument();
  });

  it("applies the tone color class", () => {
    const { container } = render(<MetricCard label="Refusals" value="99%" tone="good" />);
    const value = container.querySelector(".text-3xl");
    expect(value?.className).toContain("text-ok");
  });
});
