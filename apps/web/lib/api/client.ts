import type { z } from "zod";
import { MUTATION_HEADER, MUTATION_HEADER_VALUE } from "./constants";
import { problemItems, type ProblemItem } from "./problem";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    detail: string,
    /** Machine-readable problems of a 422 (for example the draft checks). */
    readonly errors: ProblemItem[] = [],
  ) {
    super(detail);
  }
}

async function failure(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { title?: string; detail?: string; errors?: unknown };
    return new ApiError(
      res.status,
      body.title ?? "Request failed",
      body.detail ?? res.statusText,
      problemItems(body.errors),
    );
  } catch {
    return new ApiError(res.status, "Request failed", res.statusText);
  }
}

/** GET a `/bff/*` route and validate the JSON with a generated Zod schema. */
export async function bffGet<S extends z.ZodType>(path: string, schema: S): Promise<z.infer<S>> {
  const res = await fetch(path, { headers: { Accept: "application/json" } });
  if (!res.ok) throw await failure(res);
  return schema.parse(await res.json());
}

/** State-changing call to a `/bff/*` route (sends the anti-CSRF header). */
export async function bffMutate(path: string, method: "POST" | "DELETE"): Promise<void> {
  const res = await fetch(path, { method, headers: { [MUTATION_HEADER]: MUTATION_HEADER_VALUE } });
  if (!res.ok) throw await failure(res);
}

/** POST JSON to a `/bff/*` route and validate the answer with a generated Zod schema. */
export async function bffPost<S extends z.ZodType>(
  path: string,
  payload: unknown,
  schema: S,
): Promise<z.infer<S>> {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      [MUTATION_HEADER]: MUTATION_HEADER_VALUE,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw await failure(res);
  return schema.parse(await res.json());
}
