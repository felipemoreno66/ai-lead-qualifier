"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import type { KbEntry } from "@/lib/api/schemas";
import { formatDateTimeUtc } from "@/lib/format";
import { Answer } from "./answer";
import { askDocs, fetchRecentQuestions, recentKey } from "./queries";

type Turn = { key: number; question: string; entry?: KbEntry; error?: string };

const MAX_LENGTH = 500;

function problemText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) return "Too many questions in the last hour. Try again later.";
    return error.message || "The question could not be answered.";
  }
  return "The question could not be sent. Check your connection and try again.";
}

export function AskView({ slug, workspaceName }: { slug: string; workspaceName: string }) {
  const client = useQueryClient();
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const counter = useRef(0);
  const recent = useQuery({ queryKey: recentKey(slug), queryFn: () => fetchRecentQuestions(slug) });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const question = text.trim();
    if (question.length < 3 || busy) return;
    const key = (counter.current += 1);
    setTurns((all) => [...all, { key, question }]);
    setText("");
    setBusy(true);
    try {
      const entry = await askDocs(slug, question);
      setTurns((all) => all.map((t) => (t.key === key ? { ...t, entry } : t)));
      void client.invalidateQueries({ queryKey: recentKey(slug) });
    } catch (error) {
      setTurns((all) => all.map((t) => (t.key === key ? { ...t, error: problemText(error) } : t)));
    } finally {
      setBusy(false);
    }
  }

  // The Ask button is disabled while a request runs, which drops focus; hand it back to the input
  // once the answer has landed so the next question can be typed straight away.
  useEffect(() => {
    if (!busy && counter.current > 0) input.current?.focus();
  }, [busy]);

  const history = recent.data?.filter((e) => !turns.some((t) => t.entry?.id === e.id)) ?? [];
  return (
    <>
      <div className="page-h">
        <h1>Ask the docs</h1>
        <p className="muted">
          Answers come only from {workspaceName}&rsquo;s own documents, and every claim shows where it came from.
        </p>
      </div>
      <div className="chat">
        <div className="thread" aria-live="polite" aria-busy={busy}>
          {turns.length === 0 && (
            <p className="muted empty">
              Ask about programs, prices, payment plans, scholarships or the schedule.
            </p>
          )}
          {turns.map((turn) => (
            <div className="turn" key={turn.key}>
              <div className="msg q">
                <p>{turn.question}</p>
              </div>
              {turn.entry ? (
                <Answer entry={turn.entry} />
              ) : turn.error ? (
                <div className="notice bad" role="alert">
                  <p>{turn.error}</p>
                </div>
              ) : (
                <p className="muted pending" role="status">
                  Looking through the documents…
                </p>
              )}
            </div>
          ))}
        </div>
        <form className="ask" onSubmit={submit}>
          <label className="sr" htmlFor={inputId}>
            Your question
          </label>
          <input
            id={inputId}
            ref={input}
            value={text}
            maxLength={MAX_LENGTH}
            autoComplete="off"
            placeholder="Ask about programs, prices, schedule…"
            onChange={(e) => setText(e.target.value)}
          />
          <button className="btn primary" type="submit" disabled={busy || text.trim().length < 3}>
            <Send className="ic" strokeWidth={1.6} aria-hidden="true" />
            Ask
          </button>
        </form>

        <section className="recent" aria-labelledby={`${inputId}-recent`}>
          <h2 id={`${inputId}-recent`}>Recent questions</h2>
          {recent.isError ? (
            <p className="muted" role="status">
              Recent questions could not be loaded.
            </p>
          ) : history.length === 0 ? (
            <p className="muted">{recent.isPending ? "Loading…" : "No earlier questions yet."}</p>
          ) : (
            <ul>
              {history.map((entry) => (
                <li key={entry.id}>
                  <details className="log recent-q">
                    <summary>
                      <span>{entry.question}</span>
                      <span className={`mini ${entry.covered ? "ok" : "warn"}`}>
                        {entry.covered ? "Answered" : "Not in the docs"}
                      </span>
                      <span className="muted num">{formatDateTimeUtc(entry.created_at)}</span>
                    </summary>
                    <Answer entry={entry} />
                  </details>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  );
}
