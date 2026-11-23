import "server-only";
import { NextResponse } from "next/server";
import { ZodError } from "zod";
import { AgentError } from "./server";

import { MUTATION_HEADER, MUTATION_HEADER_VALUE } from "./constants";

export function errorResponse(title: string, detail: string, status: number) {
  return NextResponse.json({ title, detail }, { status });
}

/** Map failures of an agent call to a JSON error the browser client understands. */
export async function handle(run: () => Promise<Response>): Promise<Response> {
  try {
    return await run();
  } catch (error) {
    if (error instanceof AgentError) {
      const status = error.status >= 500 ? 502 : error.status;
      return errorResponse(error.title, error.message, status);
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
  const origin = request.headers.get("origin");
  if (origin && origin !== new URL(request.url).origin) {
    return errorResponse("Forbidden", "Cross-origin requests are not allowed.", 403);
  }
  return null;
}
