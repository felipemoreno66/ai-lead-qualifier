import { FileText } from "lucide-react";
import type { KbEntry } from "@/lib/api/schemas";

/** One answer from the documents: the text, then each source with its quote on demand. */
export function Answer({ entry }: { entry: KbEntry }) {
  if (!entry.covered) {
    return (
      <div className="msg a nodoc">
        <p className="who">
          Knowledge base <span className="flag">Not in the docs</span>
        </p>
        <p>{entry.answer}</p>
        <p className="muted">
          Nothing in the documents answers this, so no sources are shown and nothing was guessed.
        </p>
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
            <details className="cite-d">
              <summary className="cite">
                <span className="cn num" aria-hidden="true">
                  {i + 1}
                </span>
                <FileText className="ic" strokeWidth={1.6} aria-hidden="true" />
                <span className="cf">{c.document_title}</span>
                {c.heading_path && <span className="ch">{c.heading_path}</span>}
                <span className="sr">, show the quote</span>
              </summary>
              <p className="cq">“{c.quote}”</p>
              <p className="cs muted">{c.document_path}</p>
            </details>
          </li>
        ))}
      </ol>
    </div>
  );
}
