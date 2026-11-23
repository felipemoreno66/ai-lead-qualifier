import { STATUS_LABELS, TIER_LABELS } from "@/lib/format";

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge s-${status}`}>
      <i aria-hidden="true" />
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function TierLabel({ tier }: { tier: string | null }) {
  if (!tier) return <span className="tier t-none">No tier</span>;
  return <span className={`tier t-${tier}`}>{TIER_LABELS[tier] ?? tier}</span>;
}

export function ScoreCell({ score }: { score: number | null }) {
  if (score === null) return <span className="score num dim">No score</span>;
  return (
    <span className="score num" title={`Score ${score} of 100`}>
      <b>{score}</b>
      <span className="bar" aria-hidden="true">
        <i style={{ width: `${score}%` }} />
      </span>
    </span>
  );
}
