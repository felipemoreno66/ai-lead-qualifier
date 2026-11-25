import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Answer, announcement } from "@/features/kb/answer";
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
  it("shows the text and each source with the passage it rests on", () => {
    render(<Answer entry={base} />);
    expect(screen.getByText("It costs USD 4,900.")).toBeInTheDocument();
    const sources = screen.getByRole("list", { name: "Sources" });
    expect(within(sources).getByText("Pricing")).toBeInTheDocument();
    expect(within(sources).getByText("Pricing > Bootcamp")).toBeInTheDocument();
    expect(within(sources).getByText(/The bootcamp costs USD 4,900\./)).toBeVisible();
    expect(sources.querySelector("details")).toBeNull();
    expect(sources.querySelector("a")).toBeNull(); // titles are not links, so they are not styled as links
    expect(screen.queryByText("Not in the docs")).not.toBeInTheDocument();
  });

  it("says explicitly when the documents do not cover the question", () => {
    render(
      <Answer
        entry={{
          ...base,
          covered: false,
          citations: [],
          answer: "I couldn't find this in the documents, so I won't guess.",
        }}
      />,
    );
    expect(screen.getByText("Not in the docs")).toBeInTheDocument();
    expect(screen.getByText(/I couldn't find this in the documents/)).toBeInTheDocument();
    expect(screen.queryByText(/nothing was guessed/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("renders quotes as text, never as markup", () => {
    const evil = { ...base.citations[0], quote: "<img src=x onerror=alert(1)> done" };
    const { container } = render(<Answer entry={{ ...base, citations: [evil] }} />);
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img src=x/)).toBeInTheDocument();
  });
});

describe("announcement", () => {
  it("says what happened in one short sentence", () => {
    expect(announcement(base)).toBe("Answer ready, 1 source.");
    const two = { ...base, citations: [...base.citations, base.citations[0]] };
    expect(announcement(two)).toBe("Answer ready, 2 sources.");
    expect(announcement({ ...base, covered: false, citations: [] })).toBe("Not in the documents.");
  });
});
