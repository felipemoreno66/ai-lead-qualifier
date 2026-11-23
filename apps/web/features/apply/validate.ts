import type { z } from "zod";
import { buildLeadSchema, type FormFieldDef } from "@/lib/forms/build-lead-schema";
import { ui } from "@/lib/i18n";

export type FieldErrors = Record<string, string>;
export type RawValues = Record<string, string | boolean>;

/** Convert what the user typed into the JSON the API expects (numbers and checkboxes typed). */
export function toAnswers(fields: FormFieldDef[], values: RawValues): Record<string, unknown> {
  const answers: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = values[f.id];
    if (f.type === "checkbox") answers[f.id] = raw === true;
    else if (f.type === "number") {
      const text = typeof raw === "string" ? raw.trim() : "";
      if (text !== "") answers[f.id] = Number(text);
    } else if (typeof raw === "string") answers[f.id] = raw;
  }
  return answers;
}

function message(issue: z.core.$ZodIssue, locale: string): string {
  const t = ui(locale);
  if (issue.code === "invalid_type" || (issue.code === "invalid_value" && issue.values?.[0] === true))
    return t.required;
  if (issue.code === "too_big") return t.tooLong(Number(issue.maximum));
  if (issue.message.includes("links")) return t.tooManyLinks;
  return t.invalid;
}

/** Validate with the same rules as the server; returns one message per field. */
export function validateAnswers(
  fields: FormFieldDef[],
  values: RawValues,
  locale: string,
): { answers: Record<string, unknown>; errors: FieldErrors } {
  const answers = toAnswers(fields, values);
  const result = buildLeadSchema(fields).safeParse(answers);
  const errors: FieldErrors = {};
  if (!result.success) {
    for (const issue of result.error.issues) {
      const id = String(issue.path[0] ?? "");
      if (id && !(id in errors)) errors[id] = message(issue, locale);
    }
  }
  return { answers, errors };
}
