import { z } from "zod";
import type { PublicWorkspaceConfig } from "@/lib/api/types";

export type FormFieldDef = PublicWorkspaceConfig["form"]["fields"][number];

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const COUNTRY_RE = /^[A-Z]{2}$/;
const URL_IN_TEXT_RE = /https?:\/\/|www\./gi;
const MAX_URLS_IN_FREE_TEXT = 3;
const DEFAULT_MAX_LENGTH: Record<string, number> = { text: 200, email: 254, textarea: 2000 };

/** Trim strings and treat blank strings and null as "not provided". */
function blankToUndefined(value: unknown): unknown {
  if (value === null) return undefined;
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed === "" ? undefined : trimmed;
  }
  return value;
}

function textSchema(field: FormFieldDef): z.ZodType {
  const limit = field.max_length ?? DEFAULT_MAX_LENGTH[field.type] ?? 200;
  let schema = z.string().max(limit, `must be at most ${limit} characters`);
  if (field.role === "free_text") {
    schema = schema.refine(
      (v) => (v.match(URL_IN_TEXT_RE) ?? []).length <= MAX_URLS_IN_FREE_TEXT,
      `must contain at most ${MAX_URLS_IN_FREE_TEXT} links`,
    );
  }
  return schema;
}

function fieldSchema(field: FormFieldDef): z.ZodType {
  let inner: z.ZodType;
  switch (field.type) {
    case "checkbox":
      inner = field.required ? z.literal(true, "required") : z.boolean();
      break;
    case "number":
      inner = z.number().finite();
      break;
    case "email":
      inner = z
        .string()
        .max(field.max_length ?? DEFAULT_MAX_LENGTH.email)
        .transform((v) => v.toLowerCase())
        .pipe(z.string().regex(EMAIL_RE, "must be a valid email address"));
      break;
    case "country":
      inner = z.string().regex(COUNTRY_RE, "must be a two-letter country code");
      break;
    case "select": {
      const allowed = new Set(field.options.map((o) => o.value));
      inner = z.string().refine((v) => allowed.has(v), "is not one of the allowed options");
      break;
    }
    default:
      inner = textSchema(field);
  }
  const preprocessed = z.preprocess(blankToUndefined, field.required ? inner : inner.optional());
  return field.required ? preprocessed : preprocessed.optional();
}

/** Zod schema mirroring the server-side validation of a workspace form. */
export function buildLeadSchema(fields: FormFieldDef[]) {
  const shape: Record<string, z.ZodType> = {};
  for (const field of fields) shape[field.id] = fieldSchema(field);
  return z.strictObject(shape);
}

export type LeadAnswers = Record<string, string | number | boolean | undefined>;

/** Field ids that failed validation (unknown keys included). */
export function errorFields(error: z.ZodError): string[] {
  const ids = new Set<string>();
  for (const issue of error.issues) {
    if (issue.code === "unrecognized_keys") issue.keys.forEach((k) => ids.add(k));
    else if (issue.path.length > 0) ids.add(String(issue.path[0]));
  }
  return [...ids].sort();
}
