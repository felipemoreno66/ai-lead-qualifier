import "server-only";
import type { z } from "zod";
import { readProblem, type ProblemItem } from "./problem";

/** Failure reported by the agent API (RFC 9457 problem details). */
export class AgentError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    detail: string,
    readonly errors: ProblemItem[] = [],
  ) {
    super(detail);
  }
}

function agentUrl(): string {
  return (process.env.AGENT_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

function adminToken(): string {
  const token = process.env.ADMIN_API_TOKEN;
  if (!token) throw new Error("ADMIN_API_TOKEN is not set");
  return token;
}

async function problem(res: Response): Promise<AgentError> {
  const p = await readProblem(res);
  return new AgentError(p.status, p.title, p.detail, p.errors);
}

/** Call `/admin/*` with the server-side bearer token and validate the response. */
export async function adminFetch<S extends z.ZodType>(
  path: string,
  schema: S,
  init: RequestInit = {},
): Promise<z.infer<S>> {
  const res = await fetch(`${agentUrl()}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${adminToken()}`, Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) throw await problem(res);
  return schema.parse(await res.json());
}

/** Same as `adminFetch` for endpoints that answer 204 No Content. */
export async function adminCall(path: string, init: RequestInit = {}): Promise<void> {
  const res = await fetch(`${agentUrl()}${path}`, {
    ...init,
    headers: { ...init.headers, Authorization: `Bearer ${adminToken()}` },
    cache: "no-store",
  });
  if (!res.ok) throw await problem(res);
}

/** Public, unauthenticated endpoints (server side, cached briefly). */
export async function publicFetch<S extends z.ZodType>(
  path: string,
  schema: S,
): Promise<z.infer<S> | null> {
  const res = await fetch(`${agentUrl()}${path}`, { next: { revalidate: 60 } });
  if (res.status === 404) return null;
  if (!res.ok) throw await problem(res);
  return schema.parse(await res.json());
}

/** Origin the browser uses to reach the agent (public intake). Read at request time. */
export function publicApiBase(): string {
  return (process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000").replace(/\/$/, "");
}
