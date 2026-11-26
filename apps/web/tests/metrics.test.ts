import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Metrics } from "@/lib/api/schemas";
import {
  dayTicks,
  timeCaption,
  volumeHeadline,
  costHeadline,
  formatDuration,
  formatUsd,
  rangeFor,
  repliedCount,
  scoreHeadline,
  shortDay,
  statusHeadline,
  timeHeadline,
} from "@/lib/metrics/summary";
import { stubLogin } from "./auth-helpers";

vi.mock("server-only", () => ({}));

const base: Metrics = {
  workspace: "northwind-academy",
  first_day: "2026-11-01",
  last_day: "2026-11-30",
  total_leads: 43,
  by_status: [
    { status: "new", count: 10 },
    { status: "approved", count: 4 },
    { status: "sent", count: 20 },
  ],
  score_histogram: [
    { min_score: 0, max_score: 9, count: 1, hot: 0, warm: 0, cold: 1 },
    { min_score: 70, max_score: 79, count: 6, hot: 3, warm: 3, cold: 0 },
    { min_score: 90, max_score: 100, count: 3, hot: 3, warm: 0, cold: 0 },
  ],
  tier_split: [
    { tier: "hot", count: 6 },
    { tier: "warm", count: 3 },
    { tier: "cold", count: 1 },
    { tier: "unscored", count: 33 },
  ],
  tier_thresholds: { hot_min: 75, warm_min: 45 },
  time_to_qualify: { count: 10, avg_seconds: 38, p50_seconds: 30, p90_seconds: 70 },
  leads_per_day: [
    { day: "2026-11-01", count: 2 },
    { day: "2026-11-02", count: 5 },
  ],
  cost: {
    total_usd: 0.4,
    avg_per_lead_usd: 0.0094,
    leads_with_runs: 43,
    llm_calls: 129,
    providers: ["anthropic"],
    ask_total_usd: 0.02,
    ask_questions: 4,
    lifetime_spent_usd: 0.4,
    budget_usd: 5,
  },
};

describe("metrics wording", () => {
  it("states each finding in a sentence", () => {
    expect(statusHeadline(base)).toBe("43 leads came in, and 24 already got a reply");
    expect(repliedCount(base)).toBe(24);
    expect(scoreHeadline(base)).toBe("60% of scored leads are hot");
    expect(timeHeadline(base)).toBe("Half of the leads were qualified within 30 seconds");
    expect(timeCaption(base)).toContain("Nine in ten took 70 seconds or less");
    expect(timeHeadline({ ...base, time_to_qualify: { ...base.time_to_qualify, p90_seconds: 30 } })).toBe(
      "Most leads were qualified within 30 seconds",
    );
    expect(volumeHeadline(base)).toBe("43 leads in 2 days, 5 on the last day");
    expect(costHeadline(base)).toBe("Each lead costs under one cent");
  });

  it("is honest about empty data and the free fake provider", () => {
    expect(statusHeadline({ ...base, total_leads: 0 })).toContain("No leads");
    expect(statusHeadline({ ...base, by_status: [] })).toBe("43 leads came in, and none has a reply yet");
    expect(scoreHeadline({ ...base, score_histogram: [] })).toBe("No lead has been scored yet");
    expect(timeHeadline({ ...base, time_to_qualify: { count: 0, avg_seconds: null, p50_seconds: null, p90_seconds: null } })).toBe(
      "No lead has been qualified yet",
    );
    const free = { ...base, cost: { ...base.cost, total_usd: 0, avg_per_lead_usd: 0, providers: ["fake"] } };
    expect(costHeadline(free)).toBe("Nothing was spent: the fake provider is free");
    expect(costHeadline({ ...base, cost: { ...base.cost, leads_with_runs: 0 } })).toContain("No model calls");
  });
});

describe("metrics helpers", () => {
  it("builds an inclusive UTC range", () => {
    expect(rangeFor(7, new Date("2026-11-23T23:59:00Z"))).toEqual({ from: "2026-11-17", to: "2026-11-23" });
    expect(rangeFor(1, new Date("2026-03-01T00:00:00Z"))).toEqual({ from: "2026-03-01", to: "2026-03-01" });
    expect(rangeFor(30, new Date("2026-03-05T10:00:00Z")).from).toBe("2026-02-04");
  });

  it("formats durations, money and days", () => {
    expect(formatDuration(0.2)).toBe("under a second");
    expect(formatDuration(38)).toBe("38 seconds");
    expect(formatDuration(600)).toBe("10 minutes");
    expect(formatDuration(7200)).toBe("2.0 hours");
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(0.0094)).toBe("$0.0094");
    expect(formatUsd(1.5)).toBe("$1.50");
    expect(shortDay("2026-11-05")).toBe("Nov 5");
  });

  it("spaces axis ticks evenly and keeps the last day", () => {
    const days = Array.from({ length: 30 }, (_, i) => `d${i}`);
    const ticks = dayTicks(days);
    expect(ticks.at(-1)).toBe("d29");
    expect(ticks.length).toBeLessThanOrEqual(7);
    const gaps = ticks.slice(1, -1).map((t, i) => days.indexOf(t) - days.indexOf(ticks[i]));
    expect(new Set(gaps).size).toBe(1);
    expect(dayTicks(["a", "b"])).toEqual(["a", "b"]);
  });
});

describe("GET /bff/metrics", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    process.env.ADMIN_API_TOKEN = "unit-test-token";
    process.env.AGENT_INTERNAL_URL = "http://agent.test";
  });

  it("forwards a validated range with the server-side token", async () => {
    const { GET } = await import("@/app/bff/metrics/route");
    let seen = "";
    let auth: string | null = null;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit) => {
        seen = String(url);
        auth = new Headers(init.headers).get("authorization");
        return Response.json(base);
      }),
    );
    const response = await GET(new Request("http://web/bff/metrics?workspace=northwind-academy&from=2026-11-01&to=2026-11-30&junk=1"));
    expect(response.status).toBe(200);
    expect(auth).toBe("Bearer unit-test-token");
    const url = new URL(seen);
    expect(url.pathname).toBe("/admin/metrics");
    expect(Object.fromEntries(url.searchParams)).toEqual({ workspace: "northwind-academy", from: "2026-11-01", to: "2026-11-30" });
  });

  it("rejects bad input before calling the agent and answers 502 on a wrong shape", async () => {
    const { GET } = await import("@/app/bff/metrics/route");
    const spy = vi.fn(async () => Response.json({ nope: true }));
    vi.stubGlobal("fetch", spy);
    for (const q of ["workspace=../admin", "from=yesterday", "to=2026-13-45", "workspace=A B"]) {
      expect((await GET(new Request(`http://web/bff/metrics?${q}`))).status).toBe(400);
    }
    expect(spy).not.toHaveBeenCalled();
    expect((await GET(new Request("http://web/bff/metrics"))).status).toBe(502);
  });

  it("is protected in production like every other route", async () => {
    const { GET } = await import("@/app/bff/metrics/route");
    await stubLogin();
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    expect((await GET(new Request("http://web/bff/metrics"))).status).toBe(401);
    expect(spy).not.toHaveBeenCalled();
  });
});
