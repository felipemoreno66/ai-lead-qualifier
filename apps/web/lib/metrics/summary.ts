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

/** Median first, so a few slow or fast leads do not skew the sentence; p90 shows the tail. */
export function timeHeadline(m: Metrics): string {
  const t = m.time_to_qualify;
  if (t.count === 0 || t.p50_seconds === null) return "No lead has been qualified yet";
  const median = formatDuration(t.p50_seconds);
  if (t.p90_seconds !== null && formatDuration(t.p90_seconds) === median)
    return `Most leads were qualified within ${median}`;
  return `Half of the leads were qualified within ${median}`;
}

export function timeCaption(m: Metrics): string {
  const t = m.time_to_qualify;
  if (t.count === 0 || t.p90_seconds === null) return "Time from application to a score";
  return `Nine in ten took ${formatDuration(t.p90_seconds)} or less, measured on ${pluralize(t.count, "lead")}.`;
}

export function volumeHeadline(m: Metrics): string {
  const days = m.leads_per_day.length;
  const today = m.leads_per_day.at(-1)?.count ?? 0;
  return `${pluralize(m.total_leads, "lead")} in ${days === 1 ? "one day" : `${days} days`}, ${today} on the last day`;
}

/** Every k-th day label (and always the last) so axis ticks are evenly spaced. */
export function dayTicks(labels: string[], target = 6): string[] {
  if (labels.length <= target) return labels;
  const step = Math.ceil((labels.length - 1) / (target - 1));
  const ticks = labels.filter((_, i) => i % step === 0 && labels.length - 1 - i >= step / 2);
  return [...ticks, labels[labels.length - 1]];
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

export const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

/** "Nov 22" for a YYYY-MM-DD day. */
export function shortDay(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
