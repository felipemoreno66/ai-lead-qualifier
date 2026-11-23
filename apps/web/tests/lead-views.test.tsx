import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoreCell, StatusBadge, TierLabel } from "@/components/status-badge";
import { describeEvent } from "@/features/leads/event-text";
import { formatDateTime, pluralize } from "@/lib/format";

describe("view helpers", () => {
  it("never relies on color alone for status, tier or missing score", () => {
    render(
      <>
        <StatusBadge status="pending_review" />
        <TierLabel tier="hot" />
        <TierLabel tier={null} />
        <ScoreCell score={null} />
        <ScoreCell score={82} />
      </>,
    );
    expect(screen.getByText("Pending review")).toBeInTheDocument();
    expect(screen.getByText("Hot")).toBeInTheDocument();
    expect(screen.getByText("No tier")).toBeInTheDocument();
    expect(screen.getByText("No score")).toBeInTheDocument();
    expect(screen.getByTitle("Score 82 of 100")).toBeInTheDocument();
  });

  it("formats dates in a fixed zone and pluralizes", () => {
    expect(formatDateTime("2026-11-22T14:02:00Z")).toBe("Nov 22, 14:02");
    expect(pluralize(1, "lead")).toBe("1 lead");
    expect(pluralize(20, "lead")).toBe("20 leads");
  });

  it("describes timeline events in plain language", () => {
    const base = { from_status: null, to_status: null, actor: "system" };
    expect(describeEvent({ ...base, type: "submitted", payload: { reference: "NW-1" } })).toContain("NW-1");
    expect(
      describeEvent({ ...base, type: "outbox_failed", payload: { attempt: 8, dead: true, error: "boom" } }),
    ).toContain("given up after 8 attempts");
    expect(
      describeEvent({ ...base, type: "outbox_failed", payload: { attempt: 2, dead: false, next_attempt_at: "2026-11-22T14:02:00Z" } }),
    ).toContain("Next try at Nov 22, 14:02 UTC");
    expect(describeEvent({ ...base, actor: "n8n", type: "outbox_delivered", payload: {} })).toContain("n8n");
    expect(
      describeEvent({ ...base, type: "status_changed", from_status: "new", to_status: "qualifying", payload: {} }),
    ).toBe("Status changed from New to Qualifying.");
  });
});
