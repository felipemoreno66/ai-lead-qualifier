import "server-only";
import { createHmac, randomBytes } from "node:crypto";
import { NextResponse } from "next/server";
import { isPublicDemo } from "./public-demo-flag";

export { isPublicDemo };

export type DemoBucket = "intake" | "ask" | "review" | "retrigger" | "read";

const WINDOW_MS = 60 * 60 * 1000;
const DEFAULT_LIMITS: Record<DemoBucket, number> = { intake: 5, ask: 10, review: 30, retrigger: 10, read: 600 };
// Ceiling for ALL visitors together, kept apart from the per-IP map so a flood of new IPs
// (or of IPv6 addresses) cannot reset it.
const DEFAULT_GLOBAL_LIMITS: Record<DemoBucket, number> = {
  intake: 100,
  ask: 150,
  review: 600,
  retrigger: 150,
  read: 6000,
};
const NAMES: Record<DemoBucket, string> = {
  intake: "INTAKE",
  ask: "ASK",
  review: "REVIEW",
  retrigger: "RETRIGGER",
  read: "READ",
};
const MAX_TRACKED = 10_000;

function configured(name: string, fallback: number, env: Record<string, string | undefined>): number {
  const value = Number(env[name]);
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

/** Requests allowed per client IP and hour for a bucket (env override, else the default). */
export function limitFor(bucket: DemoBucket, env: Record<string, string | undefined> = process.env): number {
  return configured(`DEMO_LIMIT_${NAMES[bucket]}_PER_HOUR`, DEFAULT_LIMITS[bucket], env);
}

/** Requests allowed per hour for all visitors together (env DEMO_GLOBAL_<BUCKET>_PER_HOUR). */
export function globalLimitFor(bucket: DemoBucket, env: Record<string, string | undefined> = process.env): number {
  return configured(`DEMO_GLOBAL_${NAMES[bucket]}_PER_HOUR`, DEFAULT_GLOBAL_LIMITS[bucket], env);
}

/**
 * Key of a client address: IPv4 as is, IPv6 reduced to its /64 (one household or hosting plan owns
 * a whole /64, so per-address keys would let one visitor mint unlimited identities).
 */
export function networkKey(ip: string): string {
  const mapped = /^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/i.exec(ip);
  if (mapped?.[1]) return mapped[1];
  if (!ip.includes(":")) return ip;
  const [left = "", right = ""] = ip.split("::");
  const head = left ? left.split(":") : [];
  const tail = ip.includes("::") && right ? right.split(":") : [];
  const groups = ip.includes("::") ? [...head, ...Array<string>(Math.max(8 - head.length - tail.length, 0)).fill("0"), ...tail] : head;
  const prefix = groups.slice(0, 4).map((g) => g.toLowerCase().replace(/^0+(?=.)/, ""));
  return prefix.length === 4 ? `${prefix.join(":")}::/64` : ip;
}

/**
 * The client IP as seen by the reverse proxy in front of this server. Tailscale Funnel runs on the
 * host and appends the caller's address to X-Forwarded-For before it reaches this container, so
 * the LAST entry is the real visitor; earlier entries are client-supplied and ignored. Without the
 * header (a direct local request) every caller shares the "unknown" key.
 */
export function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  const last = forwarded?.split(",").at(-1)?.trim();
  return last || "unknown";
}

// Per-process secret: log lines can tell visitors apart without revealing or outliving an address.
const LOG_SECRET = randomBytes(16);

/** Logs how a visitor was keyed (hashed key, number of X-Forwarded-For entries), once per window. */
function logClientKey(request: Request, bucket: DemoBucket, key: string): void {
  const entries = request.headers.get("x-forwarded-for")?.split(",").length ?? 0;
  const hashed = createHmac("sha256", LOG_SECRET).update(key).digest("hex").slice(0, 12);
  console.log(JSON.stringify({ event: "demo_client_key", bucket, key: hashed, forwarded_entries: entries }));
}

type Counter = { count: number; resetAt: number };
const hits = new Map<string, Counter>();
const totals = new Map<DemoBucket, Counter>();

/** Test hook. */
export function resetDemoLimits(): void {
  hits.clear();
  totals.clear();
}

function bump(map: Map<string, Counter> | Map<DemoBucket, Counter>, key: string, now: number): Counter | null {
  const m = map as Map<string, Counter>;
  let entry = m.get(key);
  if (!entry || entry.resetAt <= now) {
    if (!entry && m.size >= MAX_TRACKED) {
      for (const [k, v] of m) if (v.resetAt <= now) m.delete(k);
      // Still full of live counters: fail closed for new keys, never forget the existing ones.
      if (m.size >= MAX_TRACKED) return null;
    }
    entry = { count: 0, resetAt: now + WINDOW_MS };
    m.set(key, entry);
  }
  entry.count += 1;
  return entry;
}

function tooMany(resetAt: number, now: number): Response {
  const retryAfter = Math.max(Math.ceil((resetAt - now) / 1000), 1);
  return NextResponse.json(
    { title: "Too many requests", detail: "The public demo limits how often one visitor can do this. Try again later." },
    { status: 429, headers: { "Retry-After": String(retryAfter) } },
  );
}

/**
 * Fixed-window counters in memory (one web replica): per visitor network and bucket, plus a global
 * per-bucket ceiling. Returns a 429 response over either allowance; always null outside the
 * public demo. When the per-visitor map is full of live entries new visitors are refused.
 */
export function demoRateLimit(request: Request, bucket: DemoBucket, now = Date.now()): Response | null {
  if (!isPublicDemo()) return null;
  // Visitor first: a request refused for its own excess must not use up the shared allowance.
  const visitor = networkKey(clientIp(request));
  const entry = bump(hits, `${bucket}:${visitor}`, now);
  if (!entry) return tooMany(now + WINDOW_MS, now);
  if (entry.count === 1) logClientKey(request, bucket, visitor);
  if (entry.count > limitFor(bucket)) return tooMany(entry.resetAt, now);
  const total = bump(totals, bucket, now);
  if (!total) return tooMany(now + WINDOW_MS, now);
  if (total.count > globalLimitFor(bucket)) return tooMany(total.resetAt, now);
  return null;
}

/** Largest page the lead list may return in the public demo (the API allows 100). */
export const DEMO_MAX_PAGE_SIZE = 25;

/** 403 for actions the public demo never allows (for example deleting a lead). */
export function demoForbidden(what: string): Response | null {
  if (!isPublicDemo()) return null;
  return NextResponse.json(
    { title: "Forbidden", detail: `${what} is disabled in the public demo.` },
    { status: 403 },
  );
}
