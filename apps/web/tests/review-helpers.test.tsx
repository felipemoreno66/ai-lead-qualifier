import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { problemItems } from "@/lib/api/problem";
import type { AgentRun, LeadDetail, Message } from "@/lib/api/schemas";
import { QualificationCard } from "@/features/leads/qualification-card";
import { describeEvent } from "@/features/leads/event-text";
import {
  approveRequest,
  deliveredMessage,
  earlierVersions,
  formatCost,
  formatLatency,
  isEdited,
  pendingDraft,
  pointsLabel,
  regenerateRequest,
  rejectRequest,
  runsSummary,
  wordCount,
} from "@/lib/leads/review";

const message = (over: Partial<Message> = {}): Message =>
  ({
    id: "m1",
    version: 1,
    status: "draft",
    subject: "Your application",
    body: "Hi Mateo,\n\nThanks for applying.",
    ...over,
  }) as Message;

describe("review requests", () => {
  const draft = message();
  it("approves an untouched draft as is, ignoring line endings and edge blanks", () => {
    expect(approveRequest(draft, { subject: draft.subject!, body: `${draft.body.replace(/\n/g, "\r\n")}\n` })).toEqual({
      action: "approve",
      override: false,
    });
    expect(isEdited(draft, { subject: "Your application ", body: draft.body })).toBe(false);
  });

  it("turns changed text into an edit and carries the override flag", () => {
    expect(approveRequest(draft, { subject: "New subject", body: draft.body }, true)).toEqual({
      action: "edit",
      subject: "New subject",
      body: draft.body,
      override: true,
    });
  });

  it("drops empty notes and feedback", () => {
    expect(rejectRequest("  ")).toEqual({ action: "reject", note: null });
    expect(rejectRequest(" too pushy ")).toEqual({ action: "reject", note: "too pushy" });
    expect(regenerateRequest("")).toEqual({ action: "regenerate", feedback: null });
  });
});

describe("message selection", () => {
  const messages = [
    message({ id: "a", version: 1, status: "rejected" }),
    message({ id: "b", version: 2, status: "approved" }),
    message({ id: "c", version: 3, status: "draft" }),
  ];
  it("finds the draft, the delivered message and the earlier versions", () => {
    expect(pendingDraft(messages)?.id).toBe("c");
    expect(deliveredMessage(messages)?.id).toBe("b");
    expect(earlierVersions(messages, messages[2]).map((m) => m.id)).toEqual(["b", "a"]);
    expect(pendingDraft([])).toBeUndefined();
  });
});

describe("number formatting", () => {
  it("formats points, cost, latency and words", () => {
    expect(pointsLabel(10, 20)).toBe("10/20");
    expect(pointsLabel(7.5, 15)).toBe("7.5/15");
    expect(formatCost(0.0006)).toBe("$0.0006");
    expect(formatCost(0)).toBe("$0.0000");
    expect(formatLatency(900)).toBe("900 ms");
    expect(formatLatency(4100)).toBe("4.1 s");
    expect(wordCount("  one two\nthree ")).toBe(3);
    expect(wordCount("")).toBe(0);
  });

  it("summarises runs", () => {
    const call = { input_tokens: 10, output_tokens: 5, latency_ms: 500, cost_usd: 0.001 };
    const run = { calls: [call, call] } as unknown as AgentRun;
    expect(runsSummary([run])).toBe("2 calls, 1.0 s, $0.0020");
  });
});

describe("problem items", () => {
  it("keeps only well-formed entries", () => {
    expect(problemItems([{ code: "a", message: "b" }, { code: 1 }, null, "x"])).toEqual([{ code: "a", message: "b" }]);
    expect(problemItems(undefined)).toEqual([]);
  });
});

describe("timeline text for reviews", () => {
  const base = { from_status: null, to_status: null, actor: "operator", type: "reviewed" };
  it("names the action and an override", () => {
    expect(describeEvent({ ...base, payload: { action: "edit" } })).toBe("The reply draft was edited and approved.");
    expect(describeEvent({ ...base, payload: { action: "approve", override: true } })).toContain("despite failed checks");
  });
});

describe("QualificationCard", () => {
  const lead = {
    score: 82,
    tier: "hot",
    recommended_product_name: "Full Stack Bootcamp",
    injection_suspected: true,
    tier_capped: true,
    reasons: ["Clear goal."],
    breakdown: [
      { id: "goal_fit", description: "d", judgment: "met", points: 30, max_points: 30, evidence: "Wants a junior role." },
      { id: "availability_fit", description: "d", judgment: "partial", points: 10, max_points: 20, evidence: "Evenings only." },
    ],
  } as unknown as LeadDetail;

  it("shows the score, each criterion with points and evidence, and the injection notice", () => {
    render(<QualificationCard lead={lead} />);
    expect(screen.getByRole("heading", { name: "Why this score" })).toBeInTheDocument();
    expect(screen.getByLabelText("Score 82 out of 100")).toBeInTheDocument();
    expect(screen.getByText("Availability fit")).toBeInTheDocument();
    expect(screen.getByLabelText("10 of 20 points")).toBeInTheDocument();
    expect(screen.getByText("Partial")).toBeInTheDocument();
    expect(screen.getByText("Evenings only.")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Possible prompt injection");
    expect(screen.getByRole("note")).toHaveTextContent("capped at Warm");
  });

  it("renders nothing for a lead that is not scored", () => {
    const { container } = render(<QualificationCard lead={{ ...lead, score: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
