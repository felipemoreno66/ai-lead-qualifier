import "server-only";
import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { AgentError } from "./server";

import { guardRequest } from "@/lib/auth/dashboard-guard";
import { MUTATION_HEADER, MUTATION_HEADER_VALUE } from "./constants";

export function errorResponse(title: string, detail: string, status: number) {
  return NextResponse.json({ title, detail }, { status });
}

/** Map failures of an agent call to a JSON error the browser client understands. */
export async function handle(request: Request, run: () => Promise<Response>): Promise<Response> {
  // Every BFF route re-checks the operator credentials itself (the proxy is not the only gate).
  const denied = guardRequest(request, {
    APP_ENV: process.env.APP_ENV,
    DASHBOARD_USER: process.env.DASHBOARD_USER,
    DASHBOARD_PASSWORD: process.env.DASHBOARD_PASSWORD,
  });
  if (denied) return denied;
  try {
    return await run();
  } catch (error) {
    if (error instanceof AgentError) {
      const status = error.status >= 500 ? 502 : error.status;
      return NextResponse.json(
        { title: error.title, detail: error.message, ...(error.errors.length ? { errors: error.errors } : {}) },
        { status },
      );
    }
    if (error instanceof ZodError) {
      return errorResponse("Unexpected response", "The agent answered with an unexpected shape.", 502);
    }
    console.error("bff_error", error instanceof Error ? error.name : "unknown");
    return errorResponse("Server error", "Something went wrong on our side.", 500);
  }
}

/**
 * Cross-site requests must not trigger state changes: require the custom header (which forces a
 * CORS preflight that this app never answers) and, when present, a same-origin Origin header.
 */
export function assertSameOrigin(request: Request): Response | null {
  if (request.headers.get(MUTATION_HEADER) !== MUTATION_HEADER_VALUE) {
    return errorResponse("Forbidden", "Missing request header.", 403);
  }
  // Compare with the Host the browser used: behind Docker, `request.url` carries the container's
  // bind address (0.0.0.0), not the public one.
  const origin = request.headers.get("origin");
  const host =
    request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? new URL(request.url).host;
  if (origin && originHost(origin) !== host) {
    return errorResponse("Forbidden", "Cross-origin requests are not allowed.", 403);
  }
  return null;
}

/** Host of an Origin header, or null when it is malformed or the opaque "null" origin. */
function originHost(origin: string): string | null {
  try {
    return new URL(origin).host || null;
  } catch {
    return null;
  }
}
