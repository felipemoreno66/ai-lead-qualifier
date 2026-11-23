/** One machine-readable problem of a 422 answer, such as a failed draft check. */
export type ProblemItem = { code: string; message: string };

/** Keep only well-formed `{code, message}` entries; anything else is dropped. */
export function problemItems(raw: unknown): ProblemItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item): ProblemItem[] => {
    if (typeof item !== "object" || item === null) return [];
    const { code, message } = item as Record<string, unknown>;
    return typeof code === "string" && typeof message === "string"
      ? [{ code: code.slice(0, 60), message: message.slice(0, 300) }]
      : [];
  });
}

export type Problem = { status: number; title: string; detail: string; errors: ProblemItem[] };

/** Read an RFC 9457 problem+json answer; anything else becomes a generic failure. */
export async function readProblem(res: Response): Promise<Problem> {
  try {
    const body = (await res.json()) as { title?: string; detail?: string; errors?: unknown };
    return {
      status: res.status,
      title: body.title ?? "Request failed",
      detail: body.detail ?? res.statusText,
      errors: problemItems(body.errors),
    };
  } catch {
    return { status: res.status, title: "Request failed", detail: res.statusText, errors: [] };
  }
}
