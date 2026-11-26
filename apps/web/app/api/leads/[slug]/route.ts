import { assertSameSite, errorResponse } from "@/lib/api/bff";
import { demoRateLimit, clientIp, isPublicDemo } from "@/lib/public-demo";
import { SLUG_PATTERN } from "@/lib/kb/slug";

export const dynamic = "force-dynamic";

// Same ceiling as the agent's MAX_BODY_BYTES (16 KiB).
const MAX_BODY_BYTES = 16 * 1024;

/**
 * Public demo only: the agent is not published, so the apply form posts here and this route relays
 * it, adding the visitor's IP (for the agent's per-IP limits) and its own hourly limit.
 * Outside the public demo the form talks to the agent directly and this route does not exist.
 */
export async function POST(request: Request, ctx: { params: Promise<{ slug: string }> }) {
  if (!isPublicDemo()) return errorResponse("Not found", "Not found.", 404);
  const forbidden = assertSameSite(request);
  if (forbidden) return forbidden;
  const slug = (await ctx.params).slug;
  if (!SLUG_PATTERN.test(slug)) return errorResponse("Not found", "Unknown workspace.", 404);
  const limited = demoRateLimit(request, "intake");
  if (limited) return limited;

  if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY_BYTES) {
    return errorResponse("Payload too large", "The request is too large.", 413);
  }
  const body = await request.text();
  if (new TextEncoder().encode(body).length > MAX_BODY_BYTES) {
    return errorResponse("Payload too large", "The request is too large.", 413);
  }

  const base = (process.env.AGENT_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Forwarded-For": clientIp(request),
  };
  const origin = request.headers.get("origin");
  if (origin) headers.Origin = origin;
  let upstream: Response;
  try {
    upstream = await fetch(`${base}/api/leads/${slug}`, {
      method: "POST",
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return errorResponse("Agent unavailable", "The agent could not handle this request.", 502);
  }
  const payload = await upstream.text();
  const out: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  };
  const retry = upstream.headers.get("retry-after");
  if (retry) out["Retry-After"] = retry;
  return new Response(payload, { status: upstream.status, headers: out });
}
