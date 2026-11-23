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
