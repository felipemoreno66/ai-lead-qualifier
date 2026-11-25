import type { AgentRun, Message, ReviewInput } from "@/lib/api/schemas";

/** The fields an operator can change before sending. */
export type DraftEdits = { subject: string; body: string };

export const editsOf = (message: Pick<Message, "subject" | "body">): DraftEdits => ({
  subject: message.subject ?? "",
  body: message.body,
});

const normalize = (text: string) => text.replace(/\r\n/g, "\n").trim();

/** True when the operator's text differs from the stored draft (line endings and edge blanks ignored). */
export function isEdited(message: Pick<Message, "subject" | "body">, edits: DraftEdits): boolean {
  return (
    normalize(edits.subject) !== normalize(message.subject ?? "") ||
    normalize(edits.body) !== normalize(message.body)
  );
}

/**
 * Approve the draft as it is, or as edited. An edit is its own action on the server (it keeps the
 * original text); `override` accepts a draft that failed the checks and is recorded.
 */
export function approveRequest(
  message: Pick<Message, "subject" | "body">,
  edits: DraftEdits,
  override = false,
): ReviewInput {
  if (!isEdited(message, edits)) return { action: "approve", override };
  return { action: "edit", subject: normalize(edits.subject), body: normalize(edits.body), override };
}

const optional = (text: string) => text.trim() || null;
export const rejectRequest = (note: string): ReviewInput => ({ action: "reject", note: optional(note) });
export const regenerateRequest = (feedback: string): ReviewInput => ({
  action: "regenerate",
  feedback: optional(feedback),
});

export const wordCount = (text: string): number => text.trim().split(/\s+/).filter(Boolean).length;

export const MESSAGE_STATUS_LABEL: Record<string, string> = {
  draft: "Waiting for your review",
  approved: "Approved, sending",
  sent: "Sent",
  failed: "Sending failed",
  rejected: "Rejected",
};

/** The draft the operator is reviewing, if any. */
export const pendingDraft = (messages: Message[]): Message | undefined =>
  [...messages].reverse().find((m) => m.status === "draft");

/** The message that is, or was, on its way to the applicant (latest approved, sent or failed). */
export const deliveredMessage = (messages: Message[]): Message | undefined =>
  [...messages].reverse().find((m) => ["approved", "sent", "failed"].includes(m.status));

/** Every other version, newest first. */
export const earlierVersions = (messages: Message[], shown: Message | undefined): Message[] =>
  messages.filter((m) => m.id !== shown?.id).reverse();

export const formatCost = (usd: number): string => `$${usd.toFixed(usd >= 1 ? 2 : 4)}`;
export const formatLatency = (ms: number): string =>
  ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
export const formatTokens = (n: number): string => n.toLocaleString("en-US");

/** Whole numbers lose the decimal: 10, 7.5. */
export const formatPoints = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1));

/** "10/20" for a criterion. */
export const pointsLabel = (points: number, max: number): string =>
  `${formatPoints(points)}/${formatPoints(max)}`;

export function runTotals(run: AgentRun) {
  return run.calls.reduce(
    (sum, c) => ({
      input: sum.input + c.input_tokens,
      output: sum.output + c.output_tokens,
      latencyMs: sum.latencyMs + c.latency_ms,
      cost: sum.cost + c.cost_usd,
    }),
    { input: 0, output: 0, latencyMs: 0, cost: 0 },
  );
}

/** One-line summary of all runs for the collapsed log: "4 calls, 11.2 s, $0.0485". */
export function runsSummary(runs: AgentRun[]): string {
  const calls = runs.reduce((n, r) => n + r.calls.length, 0);
  const totals = runs.map(runTotals);
  const latency = totals.reduce((n, t) => n + t.latencyMs, 0);
  const cost = totals.reduce((n, t) => n + t.cost, 0);
  return `${calls} ${calls === 1 ? "call" : "calls"}, ${formatLatency(latency)}, ${formatCost(cost)}`;
}

const REASON_TEXT: Record<string, string> = {
  llm_timeout: "The language model took too long to answer.",
  llm_connection_error: "The language model could not be reached.",
  llm_provider_error: "The language model provider reported an error.",
  llm_output_invalid: "The model's answer did not match the expected format.",
  budget_exceeded: "The spending limit for model calls was reached.",
  send_failed: "The email could not be delivered, so the applicant has not received it.",
  internal_error: "The agent hit an unexpected problem.",
};

/** Plain-language hint for a generic error reason code (the code itself is shown next to it). */
export function explainReason(code: string | null): string | null {
  if (!code) return null;
  const known = REASON_TEXT[code.split(":")[0]];
  return known ?? null;
}

/** Badge class (`s-*`) for each message status. */
export const MESSAGE_BADGE: Record<string, string> = {
  draft: "pending_review",
  approved: "approved",
  sent: "sent",
  failed: "error",
  rejected: "rejected",
};

const PROBLEM_LABEL: Record<string, string> = {
  unsafe_link: "A link points to an unsafe address",
  disallowed_link: "A link goes to a domain the business has not allowed",
  foreign_email: "An email address that is not the business's",
  placeholder: "Unfinished placeholder text",
  control_chars: "Hidden control characters",
  empty_body: "The message is empty",
  short_body_too_long: "The short version is too long",
  short_body_markdown: "The short version contains formatting marks",
};

/** Human-readable heading of a failed draft check; unknown codes fall back to the server's text. */
export const describeProblem = (p: { code: string; message: string }): string =>
  PROBLEM_LABEL[p.code] ?? p.message;

/** Headline and one plain sentence for an error lead; never repeats provider or model details. */
export function errorSummary(code: string | null): { headline: string; sentence: string } {
  const sendFailed = code?.startsWith("send_failed");
  return {
    headline: sendFailed ? "The reply could not be delivered" : "The agent could not finish this lead",
    sentence: explainReason(code) ?? "Something went wrong while the agent worked on this lead.",
  };
}

/** The applicant's goal and questions as extracted by the agent, or null when absent. */
export function profileSummary(
  qualification: unknown,
): { goal: string; questions: string[] } | null {
  const profile = (qualification as { profile?: Record<string, unknown> } | null)?.profile;
  if (!profile || typeof profile.goal_summary !== "string" || !profile.goal_summary.trim()) return null;
  const questions = Array.isArray(profile.questions)
    ? profile.questions.filter((q): q is string => typeof q === "string").slice(0, 3)
    : [];
  return { goal: profile.goal_summary.trim(), questions };
}
