const DATE = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
});

/** "Nov 22, 14:02" in UTC (fixed zone keeps server and client renders identical). */
export function formatDateTime(iso: string): string {
  return DATE.format(new Date(iso));
}

export function formatDateTimeUtc(iso: string): string {
  return `${formatDateTime(iso)} UTC`;
}

export function countryName(code: string | null | undefined, locale = "en"): string {
  if (!code) return "Unknown country";
  try {
    return new Intl.DisplayNames([locale], { type: "region" }).of(code) ?? code;
  } catch {
    return code;
  }
}

export const STATUS_LABELS: Record<string, string> = {
  new: "New",
  qualifying: "Qualifying",
  pending_review: "Pending review",
  approved: "Approved",
  sent: "Sent",
  rejected: "Rejected",
  error: "Error",
};

export const TIER_LABELS: Record<string, string> = { hot: "Hot", warm: "Warm", cold: "Cold" };

export function pluralize(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
