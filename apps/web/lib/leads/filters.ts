export const STATUSES = [
  "new",
  "qualifying",
  "pending_review",
  "approved",
  "sent",
  "rejected",
  "error",
] as const;
export const TIERS = ["hot", "warm", "cold"] as const;
export type Status = (typeof STATUSES)[number];
export type Tier = (typeof TIERS)[number];

export const SCORE_BANDS = {
  any: { label: "Any score" },
  hot: { label: "75 and above (hot)", min: 75 },
  warm: { label: "45 to 74 (warm)", min: 45, max: 74 },
  cold: { label: "Below 45 (cold)", max: 44 },
} as const;
export type ScoreBand = keyof typeof SCORE_BANDS;

export const PAGE_SIZE = 25;

export type LeadFilters = {
  workspace?: string;
  statuses: Status[];
  band: ScoreBand;
  q: string;
  page: number;
};

type ParamsLike = { get(name: string): string | null; getAll(name: string): string[] };

const isStatus = (v: string): v is Status => (STATUSES as readonly string[]).includes(v);

/** Read filters from URL search params; unknown or malformed values are ignored. */
export function parseFilters(params: ParamsLike): LeadFilters {
  const statuses = params
    .getAll("status")
    .flatMap((v) => v.split(","))
    .filter(isStatus);
  const band = params.get("score") ?? "any";
  const page = Number.parseInt(params.get("page") ?? "1", 10);
  return {
    workspace: params.get("workspace") || undefined,
    statuses: [...new Set(statuses)],
    band: band in SCORE_BANDS ? (band as ScoreBand) : "any",
    q: (params.get("q") ?? "").slice(0, 100),
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

/** Serialise filters for the browser URL (defaults are omitted to keep URLs short). */
export function toUrlParams(f: LeadFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.workspace) p.set("workspace", f.workspace);
  if (f.statuses.length) p.set("status", f.statuses.join(","));
  if (f.band !== "any") p.set("score", f.band);
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.page > 1) p.set("page", String(f.page));
  return p;
}

/** Translate UI filters into the query understood by the agent's `/admin/leads`. */
export function toApiParams(f: LeadFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.workspace) p.set("workspace", f.workspace);
  if (f.statuses.length) p.set("status", f.statuses.join(","));
  const band = SCORE_BANDS[f.band];
  if ("min" in band) p.set("score_min", String(band.min));
  if ("max" in band) p.set("score_max", String(band.max));
  if (f.q.trim()) p.set("q", f.q.trim());
  p.set("page", String(f.page));
  p.set("page_size", String(PAGE_SIZE));
  return p;
}

export const hasActiveFilters = (f: LeadFilters) =>
  f.statuses.length > 0 || f.band !== "any" || f.q.trim() !== "";

export const queryKey = (f: LeadFilters) => ["leads", toApiParams(f).toString()] as const;
