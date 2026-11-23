import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Answer } from "@/features/kb/answer";
import type { KbEntry } from "@/lib/api/schemas";

const base: KbEntry = {
  id: "6a1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a22",
  question: "How much is the bootcamp?",
  answer: "It costs USD 4,900.",
  covered: true,
  citations: [
    {
      chunk_id: "3f1c2f5e-8a47-4f3b-9c1d-2f6f7d6c1a11",
      document_path: "02-pricing.md",
      document_title: "Pricing",
      heading_path: "Pricing > Bootcamp",
      quote: "The bootcamp costs USD 4,900.",
    },
  ],
  created_at: "2026-11-23T12:00:00Z",
};

describe("Answer", () => {
  it("shows the text and each source with its quote behind a disclosure", () => {
    render(<Answer entry={base} />);
    expect(screen.getByText("It costs USD 4,900.")).toBeInTheDocument();
    const sources = screen.getByRole("list", { name: "Sources" });
    expect(within(sources).getByText("Pricing")).toBeInTheDocument();
    expect(within(sources).getByText("Pricing > Bootcamp")).toBeInTheDocument();
    expect(within(sources).getByText(/The bootcamp costs USD 4,900\./)).toBeInTheDocument();
    expect(sources.querySelector("details")).not.toHaveAttribute("open");
    expect(screen.queryByText("Not in the docs")).not.toBeInTheDocument();
  });

  it("says explicitly when the documents do not cover the question", () => {
    render(
      <Answer
        entry={{
          ...base,
          covered: false,
          citations: [],
          answer: "Not covered in our documentation — the team will reply personally",
        }}
      />,
    );
    expect(screen.getByText("Not in the docs")).toBeInTheDocument();
    expect(screen.getByText(/Not covered in our documentation/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("renders quotes as text, never as markup", () => {
    const evil = { ...base.citations[0], quote: "<img src=x onerror=alert(1)> done" };
    const { container } = render(<Answer entry={{ ...base, citations: [evil] }} />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });
});
