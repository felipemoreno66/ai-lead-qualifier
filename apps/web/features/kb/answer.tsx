import { FileText } from "lucide-react";
import type { KbEntry } from "@/lib/api/schemas";

/** Short text for the live region: what just happened, in a sentence. */
export function announcement(entry: KbEntry): string {
  if (!entry.covered) return "Not in the documents.";
  const n = entry.citations.length;
  return `Answer ready, ${n} ${n === 1 ? "source" : "sources"}.`;
}

/** One answer from the documents: the text, then each source with the passage it rests on. */
export function Answer({ entry }: { entry: KbEntry }) {
  if (!entry.covered) {
    return (
      <div className="msg a nodoc">
        <p className="who">
          Knowledge base <span className="flag">Not in the docs</span>
        </p>
        <p>{entry.answer}</p>
      </div>
    );
  }
  return (
    <div className="msg a">
      <p className="who">Knowledge base</p>
      <p>{entry.answer}</p>
      <ol className="cites" aria-label="Sources">
        {entry.citations.map((c, i) => (
          <li key={`${c.chunk_id}-${i}`}>
            <p className="cite">
              <span className="cn num" aria-hidden="true">
                {i + 1}
              </span>
              <FileText className="ic" strokeWidth={1.6} aria-hidden="true" />
              <span className="cf">{c.document_title}</span>
              {c.heading_path && <span className="ch">{c.heading_path}</span>}
            </p>
            <p className="cq">“{c.quote}”</p>
            <p className="cs muted">{c.document_path}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}
