"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { StatusBadge } from "@/components/status-badge";
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
import { bffMutate } from "@/lib/api/client";
import type { LeadDetail } from "@/lib/api/schemas";
import { countryName, formatDateTime, formatDateTimeUtc } from "@/lib/format";
import { deliveredMessage, earlierVersions, explainReason, pendingDraft } from "@/lib/leads/review";
import { DraftReview, EarlierDrafts, MessageLetter } from "./draft-review";
import { describeEvent } from "./event-text";
import { QualificationCard } from "./qualification-card";
import { RunsLog } from "./runs-log";
import { fetchLead, leadKey } from "./queries";

const IN_FLIGHT = new Set(["new", "qualifying", "approved"]);

export function LeadDetailView({ id }: { id: string }) {
  const query = useQuery({
    queryKey: leadKey(id),
    queryFn: () => fetchLead(id),
    // The agent works in the background: follow the lead until it settles on a status that waits for a person.
    refetchInterval: (q) => (q.state.data && IN_FLIGHT.has(q.state.data.status) ? 2000 : false),
  });
  if (query.isError)
    return (
      <section className="errbox" role="alert">
        <AlertTriangle className="ic" aria-hidden="true" />
        <div>
          <h1>This lead could not be loaded</h1>
          <p>{query.error.message}</p>
          <button className="btn primary" type="button" onClick={() => query.refetch()}>
            Try again
          </button>
        </div>
      </section>
    );
  if (!query.data)
    return (
      <div role="status" aria-busy="true" aria-label="Loading lead">
        <span className="skel" style={{ height: 48, width: "50%", marginBottom: 24 }} />
        <span className="skel" style={{ height: 200 }} />
      </div>
    );
  return <Detail lead={query.data} />;
}

function Detail({ lead }: { lead: LeadDetail }) {
  const router = useRouter();
  const client = useQueryClient();
  const refresh = () => {
    void client.invalidateQueries({ queryKey: leadKey(lead.id) });
    void client.invalidateQueries({ queryKey: ["leads"] });
  };
  const retrigger = useMutation({
    mutationFn: () => bffMutate(`/bff/leads/${lead.id}/retrigger`, "POST"),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: () => bffMutate(`/bff/leads/${lead.id}`, "DELETE"),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["leads"] });
      client.removeQueries({ queryKey: leadKey(lead.id) });
      router.push("/dashboard");
    },
  });

  const lastOutbox = lead.outbox.at(-1);
  const orchestrationDead = lead.status === "new" && lastOutbox?.status === "dead";
  const canRetrigger = lead.status === "new" || lead.status === "error";
  const [notice, setNotice] = useState("");
  const draft = lead.status === "pending_review" ? pendingDraft(lead.messages) : undefined;
  const letter = draft ? undefined : deliveredMessage(lead.messages);
  const earlier = earlierVersions(lead.messages, draft ?? letter);

  return (
    <>
      <p className="crumb">
        <Link href="/dashboard" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
          <ArrowLeft className="ic" aria-hidden="true" />
          Back to leads
        </Link>
      </p>
      <header className="dh">
        <h1>{lead.name}</h1>
        <StatusBadge status={lead.status} />
      </header>
      <p className="meta">
        Applied <time dateTime={lead.created_at}>{formatDateTimeUtc(lead.created_at)}</time> from{" "}
        {countryName(lead.country)} &middot; {lead.email} &middot; ref {lead.reference}
      </p>

      {lead.status === "error" && (
        <section className="errbox" role="alert" style={{ marginBottom: 32 }}>
          <AlertTriangle className="ic" aria-hidden="true" />
          <div>
            <h2>Something went wrong with this lead</h2>
            <p>
              {lead.error_reason ? <code>{lead.error_reason}</code> : "No reason was recorded."}
              {explainReason(lead.error_reason) && <> {explainReason(lead.error_reason)}</>}
            </p>
            <p>Nothing was sent to the applicant. Retry to queue the lead again.</p>
            <RetriggerButton pending={retrigger.isPending} onClick={() => retrigger.mutate()} primary />
            <MutationStatus mutation={retrigger} done="Queued again. It should be picked up within seconds." />
          </div>
        </section>
      )}

      {orchestrationDead && (
        <section className="warnbox" role="alert">
          <AlertTriangle className="ic" aria-hidden="true" />
          <div>
            <h2>Orchestration failed</h2>
            <p>
              The new-lead event could not be delivered after {lastOutbox?.attempts} attempts
              {lastOutbox?.last_error ? ` (${lastOutbox.last_error})` : ""}. The application is
              safe; re-trigger once the orchestrator is back.
            </p>
            <RetriggerButton pending={retrigger.isPending} onClick={() => retrigger.mutate()} primary />
            <MutationStatus mutation={retrigger} done="Queued again. It should be picked up within seconds." />
          </div>
        </section>
      )}

      <p className="status-line ok" role="status" aria-live="polite">
        {notice}
      </p>
      {draft && <DraftReview key={draft.id} lead={lead} message={draft} announce={setNotice} />}
      {letter && <MessageLetter lead={lead} message={letter} />}

      <section className="section" aria-labelledby="app-h">
        <h2 id="app-h">Application</h2>
        <div className="panel">
          <dl className="kv">
            {lead.answers.map((a) => (
              <div key={a.id} style={{ display: "contents" }}>
                <dt>{a.label}</dt>
                <dd>{a.id === "country" ? countryName(a.display) : a.display}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <QualificationCard lead={lead} />
      <EarlierDrafts messages={earlier} />
      <RunsLog leadId={lead.id} />

      <section className="section" aria-labelledby="timeline-h">
        <h2 id="timeline-h">Timeline</h2>
        <ol className="timeline">
          {lead.events.map((e) => (
            <li key={e.id}>
              <time dateTime={e.created_at}>{formatDateTime(e.created_at)}</time>
              <span>{describeEvent(e)}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="section" aria-labelledby="orch-h">
        <h2 id="orch-h">Orchestration</h2>
        <div className="panel">
          {lead.outbox.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              No events were queued for this lead.
            </p>
          ) : (
            <ul className="timeline">
              {lead.outbox.map((o) => (
                <li key={o.id}>
                  <span className="num muted">{o.event_type}</span>
                  <span>
                    {o.status === "delivered" && `Delivered${o.delivered_at ? ` at ${formatDateTimeUtc(o.delivered_at)}` : ""}.`}
                    {o.status === "pending" &&
                      `Waiting. ${o.attempts > 0 ? `${o.attempts} failed attempt${o.attempts === 1 ? "" : "s"}; next try at ${formatDateTimeUtc(o.next_attempt_at)}.` : "First delivery pending."}`}
                    {o.status === "processing" && "Being delivered now."}
                    {o.status === "dead" && `Gave up after ${o.attempts} attempts.`}
                    {o.last_error && o.status !== "delivered" ? ` Last error: ${o.last_error}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {canRetrigger && lead.status !== "error" && !orchestrationDead && (
            <div className="rowbtns">
              <RetriggerButton pending={retrigger.isPending} onClick={() => retrigger.mutate()} />
              <MutationStatus mutation={retrigger} done="Queued again." />
            </div>
          )}
        </div>
      </section>

      <section className="section" aria-labelledby="privacy-h">
        <h2 id="privacy-h">Consent and data</h2>
        <div className="panel">
          <p style={{ margin: "0 0 16px" }}>
            The applicant accepted privacy notice version <b>{lead.consent_notice_version}</b> on{" "}
            {formatDateTimeUtc(lead.consent_at)}. Source: {lead.source.replace("_", " ")}.
          </p>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button className="btn danger" type="button">
                <Trash2 className="ic" aria-hidden="true" />
                Delete this lead
              </button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogTitle>Delete {lead.name}?</AlertDialogTitle>
              <AlertDialogDescription>
                This permanently removes the application, its timeline and queued events. It cannot
                be undone.
              </AlertDialogDescription>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep lead</AlertDialogCancel>
                <AlertDialogAction onClick={() => remove.mutate()}>Delete permanently</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          <MutationStatus mutation={remove} done="Deleted." />
        </div>
      </section>
    </>
  );
}

function RetriggerButton({
  onClick,
  pending,
  primary,
}: {
  onClick: () => void;
  pending: boolean;
  primary?: boolean;
}) {
  return (
    <button className={`btn${primary ? " primary" : ""}`} type="button" disabled={pending} onClick={onClick}>
      <RotateCcw className="ic" aria-hidden="true" />
      {pending ? "Queuing" : "Re-trigger"}
    </button>
  );
}

function MutationStatus({
  mutation,
  done,
}: {
  mutation: { isSuccess: boolean; isError: boolean; error: Error | null };
  done: string;
}) {
  return (
    <p className={`status-line${mutation.isSuccess ? " ok" : ""}`} role="status" aria-live="polite">
      {mutation.isSuccess ? done : mutation.isError ? `Could not complete this: ${mutation.error?.message}` : ""}
    </p>
  );
}
