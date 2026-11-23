import { ShieldAlert } from "lucide-react";
import { TierLabel } from "@/components/status-badge";
import type { LeadDetail } from "@/lib/api/schemas";
import { formatPoints, pointsLabel } from "@/lib/leads/review";
import { humanize } from "./event-text";

const JUDGMENT: Record<string, string> = { met: "Met", partial: "Partial", unmet: "Not met" };

/** "Why this score": the score, the tier and the evidence behind every criterion. */
export function QualificationCard({ lead }: { lead: LeadDetail }) {
  if (lead.score === null) return null;
  return (
    <section className="why" aria-labelledby="why-h">
      <h2 id="why-h">Why this score</h2>
      <div className="verdict">
        <p className="bignum num" aria-label={`Score ${lead.score} out of 100`}>
          {lead.score}
        </p>
        <p>
          out of 100. <TierLabel tier={lead.tier} />.
          {lead.recommended_product_name && (
            <>
              {" "}
              The assistant recommends the <b>{lead.recommended_product_name}</b>.
            </>
          )}
        </p>
      </div>
      {lead.injection_suspected && (
        <div className="notice" role="note">
          <ShieldAlert className="ic" aria-hidden="true" />
          <p>
            <b>Possible prompt injection.</b> The free text of this application looked like an
            instruction to the assistant, so it was ignored when scoring
            {lead.tier_capped ? " and the tier was capped at Warm" : ""}. Read the application
            yourself before replying.
          </p>
        </div>
      )}
      {lead.breakdown.length > 0 && (
        <ol className="criteria">
          {lead.breakdown.map((c) => (
            <li className={`crit c-${c.judgment}`} key={c.id}>
              <div className="crit-h">
                <span className="crit-n">{humanize(c.id)}</span>
                <span className="crit-p num" aria-label={`${pointsLabel(c.points, c.max_points).replace("/", " of ")} points`}>
                  {formatPoints(c.points)}
                  <small>/{formatPoints(c.max_points)}</small>
                </span>
                <span className="crit-l">{JUDGMENT[c.judgment] ?? c.judgment}</span>
              </div>
              <p>{c.evidence}</p>
            </li>
          ))}
        </ol>
      )}
      {lead.reasons.length > 0 && (
        <>
          <h3 className="sub">In short</h3>
          <ul className="reasons">
            {lead.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
