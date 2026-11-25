import { STATUS_LABELS, formatDateTimeUtc } from "@/lib/format";

type TimelineEvent = {
  type: string;
  from_status: string | null;
  to_status: string | null;
  actor: string;
  payload: Record<string, unknown>;
};

const REVIEW_ACTION: Record<string, string> = {
  approve: "approved",
  edit: "edited and approved",
  reject: "rejected",
  regenerate: "sent back for a new draft",
};

/** Plain-language description of a `lead_events` row for the timeline. */
export function describeEvent(e: TimelineEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "submitted":
      return typeof p.reference === "string"
        ? `Application received (reference ${p.reference}).`
        : "Application received.";
    case "outbox_delivered":
      return e.actor === "n8n"
        ? "n8n confirmed it processed the new-lead event."
        : "The new-lead event was delivered to the orchestrator.";
    case "outbox_failed": {
      const attempt = Number(p.attempt ?? 0);
      const reason = typeof p.error === "string" ? ` ${p.error}.` : "";
      if (p.dead === true)
        return `Delivery failed and was given up after ${attempt} attempts.${reason}`;
      const next =
        typeof p.next_attempt_at === "string"
          ? ` Next try at ${formatDateTimeUtc(p.next_attempt_at)}.`
          : "";
      return `Delivery attempt ${attempt} failed.${reason}${next}`;
    }
    case "retriggered":
      return `An operator re-triggered orchestration (attempt ${Number(p.attempt ?? 0)}).`;
    case "status_changed":
      return `Status changed from ${STATUS_LABELS[e.from_status ?? ""] ?? e.from_status} to ${STATUS_LABELS[e.to_status ?? ""] ?? e.to_status}.`;
    case "reviewed": {
      const action = REVIEW_ACTION[String(p.action)] ?? "reviewed";
      return `The reply draft was ${action}${p.override === true ? " despite failed checks" : ""}.`;
    }
    case "email_sent":
      return "The reply email was sent.";
    default:
      return e.type;
  }
}

export const humanize = (id: string) => {
  const text = id.replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};
