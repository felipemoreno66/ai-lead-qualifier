"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Pencil, RefreshCw, Send, Undo2, X } from "lucide-react";
import { useId, useState } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { ApiError } from "@/lib/api/client";
import type { LeadDetail, Message, ReviewInput } from "@/lib/api/schemas";
import { formatDateTimeUtc } from "@/lib/format";
import {
  MESSAGE_STATUS_LABEL,
  approveRequest,
  editsOf,
  isEdited,
  regenerateRequest,
  rejectRequest,
  wordCount,
  type DraftEdits,
} from "@/lib/leads/review";
import { leadKey, submitReview } from "./queries";

const LANGUAGE: Record<string, string> = { en: "English", es: "Spanish", pt: "Portuguese" };

const RESULT_TEXT: Record<ReviewInput["action"], string> = {
  approve: "Approved. The email is being sent.",
  edit: "Approved with your edits. The email is being sent.",
  reject: "Rejected. Nothing was sent to the applicant.",
  regenerate: "A new draft is ready for your review.",
};

/** The draft reply as a letter, with the four review actions. `announce` feeds the page's live region. */
export function DraftReview({
  lead,
  message,
  announce,
}: {
  lead: LeadDetail;
  message: Message;
  announce: (text: string) => void;
}) {
  const client = useQueryClient();
  const ids = { subject: useId(), body: useId(), feedback: useId(), note: useId() };
  const [editing, setEditing] = useState(false);
  const [edits, setEdits] = useState<DraftEdits>(() => editsOf(message));
  const [regenerating, setRegenerating] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [note, setNote] = useState("");

  const review = useMutation({
    mutationFn: (request: ReviewInput) => submitReview(lead.id, request),
    onMutate: () => announce(""),
    onSuccess: (result, request) => {
      announce(
        result.error_reason
          ? `The new draft could not be written (${result.error_reason}). The lead is marked as an error; retry it from the banner.`
          : RESULT_TEXT[request.action],
      );
      setEditing(false);
      setRegenerating(false);
      void client.invalidateQueries({ queryKey: leadKey(lead.id) });
      void client.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  const problems =
    review.error instanceof ApiError && review.error.status === 422 ? review.error.errors : [];
  const failure = review.error && problems.length === 0 ? review.error.message : null;
  const changed = isEdited(message, edits);
  const busy = review.isPending;
  const approve = (override: boolean) => review.mutate(approveRequest(message, edits, override));

  return (
    <section className="review" aria-labelledby="rv">
      <h2 id="rv">Draft reply to {lead.name.split(" ")[0]}</h2>
      <p className="muted">
        Read it, change anything you like, then send. Nothing leaves until you approve.
      </p>
      <div className="draft">
        <Meta message={message} words={wordCount(editing ? edits.body : message.body)} />
        <label className="draft-l" htmlFor={ids.subject}>
          Subject
        </label>
        <input
          id={ids.subject}
          className="draft-subj"
          value={editing ? edits.subject : (message.subject ?? "")}
          readOnly={!editing}
          maxLength={150}
          onChange={(e) => setEdits({ ...edits, subject: e.target.value })}
        />
        <label className="draft-l" htmlFor={ids.body}>
          Message
        </label>
        <textarea
          id={ids.body}
          className="draft-body"
          rows={14}
          value={editing ? edits.body : message.body}
          readOnly={!editing}
          maxLength={4000}
          onChange={(e) => setEdits({ ...edits, body: e.target.value })}
        />
        {message.guard_warnings.length > 0 && (
          <p className="draft-src">Checks that flagged this draft: {message.guard_warnings.join("; ")}.</p>
        )}
      </div>

      {problems.length > 0 && (
        <div className="notice bad" role="alert">
          <AlertTriangle className="ic" aria-hidden="true" />
          <div>
            <p>
              <b>This message did not pass the safety checks.</b> Fix it, or send it anyway if you
              have checked it yourself. Sending anyway is recorded in the timeline.
            </p>
            <ul>
              {problems.map((p) => (
                <li key={`${p.code}-${p.message}`}>{p.message}</li>
              ))}
            </ul>
            <button className="btn" type="button" disabled={busy} onClick={() => approve(true)}>
              <Send className="ic" aria-hidden="true" />
              Send anyway
            </button>
          </div>
        </div>
      )}
      {failure && (
        <p className="field-error" role="alert">
          Could not complete this: {failure}
        </p>
      )}

      <div className="actions" role="group" aria-label="Review this draft">
        <button className="btn primary" type="button" disabled={busy} onClick={() => approve(false)}>
          <Send className="ic" aria-hidden="true" />
          {busy ? "Working" : changed ? "Approve and send edits" : "Approve and send"}
        </button>
        {editing ? (
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => {
              setEdits(editsOf(message));
              setEditing(false);
            }}
          >
            <Undo2 className="ic" aria-hidden="true" />
            Discard edits
          </button>
        ) : (
          <button className="btn" type="button" disabled={busy} onClick={() => setEditing(true)}>
            <Pencil className="ic" aria-hidden="true" />
            Edit
          </button>
        )}
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <button className="btn danger" type="button" disabled={busy}>
              <X className="ic" aria-hidden="true" />
              Reject
            </button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogTitle>Reject this draft?</AlertDialogTitle>
            <AlertDialogDescription>
              Nothing is sent and the lead is closed as rejected. A short note is optional.
            </AlertDialogDescription>
            <label htmlFor={ids.note}>Note (optional)</label>
            <textarea
              id={ids.note}
              rows={3}
              maxLength={500}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <AlertDialogFooter>
              <AlertDialogCancel>Keep reviewing</AlertDialogCancel>
              <AlertDialogAction onClick={() => review.mutate(rejectRequest(note))}>
                Reject draft
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        <button
          className="btn"
          type="button"
          disabled={busy}
          aria-expanded={regenerating}
          aria-controls={`${ids.feedback}-panel`}
          onClick={() => setRegenerating((open) => !open)}
        >
          <RefreshCw className="ic" aria-hidden="true" />
          Regenerate
        </button>
      </div>

      {regenerating && (
        <div className="regen" id={`${ids.feedback}-panel`}>
          <label htmlFor={ids.feedback}>What should change? (optional)</label>
          <textarea
            id={ids.feedback}
            rows={3}
            maxLength={500}
            value={feedback}
            placeholder="For example: shorter, and mention the payment plan."
            onChange={(e) => setFeedback(e.target.value)}
          />
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => review.mutate(regenerateRequest(feedback))}
          >
            <RefreshCw className="ic" aria-hidden="true" />
            {busy ? "Writing a new draft" : "Write a new draft"}
          </button>
        </div>
      )}
    </section>
  );
}

function Meta({ message, words }: { message: Message; words: number }) {
  return (
    <dl className="draft-meta">
      <div>
        <dt>To</dt>
        <dd>{message.channel_recipient}</dd>
      </div>
      <div>
        <dt>Language</dt>
        <dd>{LANGUAGE[message.language] ?? message.language}</dd>
      </div>
      <div>
        <dt>Version</dt>
        <dd className="num">
          {message.version} &middot; {words} words
        </dd>
      </div>
    </dl>
  );
}

/** A message that is no longer a draft: read-only letter, delivery status and the edit trail. */
export function MessageLetter({ lead, message }: { lead: LeadDetail; message: Message }) {
  const badge =
    message.status === "sent" ? "sent" : message.status === "failed" ? "error" : message.status === "rejected" ? "rejected" : "approved";
  return (
    <section className="review letter" aria-labelledby="msg-h">
      <header className="dh">
        <h2 id="msg-h">Reply to {lead.name.split(" ")[0]}</h2>
        <span className={`badge s-${badge}`}>
          <i aria-hidden="true" />
          {MESSAGE_STATUS_LABEL[message.status] ?? message.status}
        </span>
      </header>
      <p className="muted">
        {message.status === "sent" && message.sent_at
          ? `Sent ${formatDateTimeUtc(message.sent_at)}.`
          : message.status === "failed"
            ? "The email could not be delivered. Retry the lead from the banner to draft it again."
            : message.reviewed_at
              ? `Approved ${formatDateTimeUtc(message.reviewed_at)}.`
              : ""}
      </p>
      <div className="draft">
        <Meta message={message} words={wordCount(message.body)} />
        <p className="draft-l">Subject</p>
        <p className="letter-subj">{message.subject}</p>
        <p className="draft-l">Message</p>
        <p className="letter-body">{message.body}</p>
      </div>
      {message.edited_by_operator && (
        <details className="orig">
          <summary>Edited by you before sending. See the original draft.</summary>
          <p className="letter-body">{message.original_body ?? "The original text was not kept."}</p>
        </details>
      )}
    </section>
  );
}

/** Older versions (rejected or replaced drafts), collapsed. */
export function EarlierDrafts({ messages }: { messages: Message[] }) {
  if (messages.length === 0) return null;
  return (
    <details className="log" id="earlier">
      <summary>
        Earlier drafts <span className="muted">{messages.length}</span>
      </summary>
      <ul className="versions">
        {messages.map((m) => (
          <li key={m.id}>
            <p>
              <b>Version {m.version}</b> &middot; {MESSAGE_STATUS_LABEL[m.status] ?? m.status}
              {m.review_note ? ` · note: ${m.review_note}` : ""}
            </p>
            <p className="letter-body">{m.body}</p>
          </li>
        ))}
      </ul>
    </details>
  );
}
