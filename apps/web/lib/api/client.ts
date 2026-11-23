import type { z } from "zod";
import { MUTATION_HEADER, MUTATION_HEADER_VALUE } from "./constants";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly title: string,
    detail: string,
  ) {
    super(detail);
  }
}

async function failure(res: Response): Promise<ApiError> {
  try {
    const body = (await res.json()) as { title?: string; detail?: string };
    return new ApiError(res.status, body.title ?? "Request failed", body.detail ?? res.statusText);
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
