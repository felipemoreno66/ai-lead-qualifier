import type { Metrics } from "@/lib/api/schemas";
import { pluralize, STATUS_LABELS } from "@/lib/format";

export const RANGES = [7, 14, 30, 90] as const;

const isoDay = (d: Date) => d.toISOString().slice(0, 10);

/** Inclusive UTC day range of `days` days ending today. */
export function rangeFor(days: number, today: Date): { from: string; to: string } {
  const start = new Date(
    Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - (days - 1)),
  );
  return { from: isoDay(start), to: isoDay(today) };
}

export function formatDuration(seconds: number): string {
  if (seconds < 1) return "under a second";
  if (seconds < 90) return `${Math.round(seconds)} seconds`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} minutes`;
  return `${(seconds / 3600).toFixed(1)} hours`;
}

export function formatUsd(usd: number): string {
  if (usd === 0) return "$0.00";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

const countOf = (m: Metrics, status: string) =>
  m.by_status.find((s) => s.status === status)?.count ?? 0;

/** Leads whose reply was approved or already sent. */
export const repliedCount = (m: Metrics) => countOf(m, "approved") + countOf(m, "sent");

export function statusHeadline(m: Metrics): string {
  if (m.total_leads === 0) return "No leads came in during this period";
  const replied = repliedCount(m);
  const tail = replied === 0 ? "none has a reply yet" : `${replied} already ${replied === 1 ? "has a reply" : "got a reply"}`;
  return `${pluralize(m.total_leads, "lead")} came in, and ${tail}`;
}

export const scoredCount = (m: Metrics) => m.score_histogram.reduce((n, b) => n + b.count, 0);

export function scoreHeadline(m: Metrics): string {
  const total = scoredCount(m);
  if (total === 0) return "No lead has been scored yet";
  const tiers = m.tier_split.filter((t) => t.tier !== "unscored");
  const top = tiers.reduce((a, b) => (b.count > a.count ? b : a));
  return `${Math.round((top.count / total) * 100)}% of scored leads are ${top.tier}`;
}

export function timeHeadline(m: Metrics): string {
  const t = m.time_to_qualify;
  if (t.count === 0 || t.avg_seconds === null) return "No lead has been qualified yet";
  return `Qualification takes ${formatDuration(t.avg_seconds)} on average`;
}

export function costHeadline(m: Metrics): string {
  const c = m.cost;
  if (c.leads_with_runs === 0) return "No model calls were made for these leads";
  if (c.total_usd === 0)
    return c.providers.every((p) => p === "fake")
      ? "Nothing was spent: the fake provider is free"
      : "No cost was recorded for these leads";
  return c.avg_per_lead_usd !== null && c.avg_per_lead_usd < 0.01
    ? "Each lead costs under one cent"
    : `Each lead costs ${formatUsd(c.avg_per_lead_usd ?? 0)} on average`;
}

/** Tier of a score bucket from the workspace thresholds (`none` when they are unknown). */
export function bucketTier(
  minScore: number,
  thresholds: Metrics["tier_thresholds"],
): "hot" | "warm" | "cold" | "none" {
  if (!thresholds) return "none";
  return minScore >= thresholds.hot_min ? "hot" : minScore >= thresholds.warm_min ? "warm" : "cold";
}

export const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

/** "Nov 22" for a YYYY-MM-DD day. */
export function shortDay(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
