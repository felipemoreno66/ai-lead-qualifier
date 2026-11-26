import "server-only";
import { NextResponse } from "next/server";
import { isPublicDemo } from "./public-demo-flag";

export { isPublicDemo };

export type DemoBucket = "intake" | "ask" | "review" | "retrigger";

const WINDOW_MS = 60 * 60 * 1000;
const DEFAULT_LIMITS: Record<DemoBucket, number> = { intake: 5, ask: 10, review: 30, retrigger: 10 };
const ENV_NAMES: Record<DemoBucket, string> = {
  intake: "DEMO_LIMIT_INTAKE_PER_HOUR",
  ask: "DEMO_LIMIT_ASK_PER_HOUR",
  review: "DEMO_LIMIT_REVIEW_PER_HOUR",
  retrigger: "DEMO_LIMIT_RETRIGGER_PER_HOUR",
};
const MAX_TRACKED = 10_000;

/** Requests allowed per client IP and hour for a bucket (env override, else the default). */
export function limitFor(bucket: DemoBucket, env: Record<string, string | undefined> = process.env): number {
  const configured = Number(env[ENV_NAMES[bucket]]);
  return Number.isInteger(configured) && configured > 0 ? configured : DEFAULT_LIMITS[bucket];
}

/**
 * The client IP as seen by the reverse proxy in front of this server (Tailscale Funnel appends
 * the caller to X-Forwarded-For). Only the LAST entry is believed: earlier ones are client-supplied.
 */
export function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  const last = forwarded?.split(",").at(-1)?.trim();
  return last || "unknown";
}

const hits = new Map<string, { count: number; resetAt: number }>();

/** Test hook. */
export function resetDemoLimits(): void {
  hits.clear();
}

/**
 * Fixed-window counter per IP and bucket, in memory (one web replica). Returns a 429 response when
 * the caller is over its hourly allowance; always null outside the public demo.
 */
export function demoRateLimit(request: Request, bucket: DemoBucket, now = Date.now()): Response | null {
  if (!isPublicDemo()) return null;
  const key = `${bucket}:${clientIp(request)}`;
  let entry = hits.get(key);
  if (!entry || entry.resetAt <= now) {
    if (hits.size >= MAX_TRACKED) {
      for (const [k, v] of hits) if (v.resetAt <= now) hits.delete(k);
      if (hits.size >= MAX_TRACKED) hits.clear(); // under a flood, forget rather than grow
    }
    entry = { count: 0, resetAt: now + WINDOW_MS };
    hits.set(key, entry);
  }
  entry.count += 1;
  if (entry.count <= limitFor(bucket)) return null;
  const retryAfter = Math.max(Math.ceil((entry.resetAt - now) / 1000), 1);
  return NextResponse.json(
    { title: "Too many requests", detail: "The public demo limits how often one visitor can do this. Try again later." },
    { status: 429, headers: { "Retry-After": String(retryAfter) } },
  );
}

/** 403 for actions the public demo never allows (for example deleting a lead). */
export function demoForbidden(what: string): Response | null {
  if (!isPublicDemo()) return null;
  return NextResponse.json(
    { title: "Forbidden", detail: `${what} is disabled in the public demo.` },
    { status: 403 },
  );
}
