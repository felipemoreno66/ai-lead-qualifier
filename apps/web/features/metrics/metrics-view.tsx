"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";
import { Bar, BarChart, Cell, LabelList, XAxis, YAxis } from "recharts";
import type { Metrics, WorkspaceSummary } from "@/lib/api/schemas";
import { pluralize } from "@/lib/format";
import {
  bucketTier,
  costHeadline,
  formatDuration,
  formatUsd,
  rangeFor,
  RANGES,
  scoreHeadline,
  scoredCount,
  shortDay,
  statusHeadline,
  statusLabel,
  timeHeadline,
} from "@/lib/metrics/summary";
import { fetchMetrics, metricsKey } from "../leads/queries";

const STATUS_FILL: Record<string, string> = {
  new: "var(--wq-muted)",
  qualifying: "var(--wq-info)",
  pending_review: "var(--wq-amber)",
  approved: "var(--wq-sage)",
  sent: "var(--wq-sage)",
  rejected: "var(--wq-muted)",
  error: "var(--wq-bad)",
};
const TIER_FILL = {
  hot: "var(--wq-accent)",
  warm: "var(--wq-amber)",
  cold: "var(--wq-info)",
  none: "var(--wq-plum)",
};

type Props = { workspaces: WorkspaceSummary[]; defaultWorkspace: string };

export function MetricsView({ workspaces, defaultWorkspace }: Props) {
  const [days, setDays] = useState<number>(30);
  const [workspace, setWorkspace] = useState(defaultWorkspace);
  const [today] = useState(() => new Date());
  const params = { workspace, ...rangeFor(days, today) };
  const query = useQuery({
    queryKey: metricsKey(params),
    queryFn: () => fetchMetrics(params),
    placeholderData: keepPreviousData,
  });
  const usable = workspaces.filter((w) => w.enabled);
  const name = usable.find((w) => w.slug === workspace)?.name ?? workspace;

  return (
    <>
      <div className="page-h">
        <h1>How is it going?</h1>
        <p className="muted">
          Last {days} days, {name}
        </p>
      </div>
      <div className="filters">
        <div className="segs" role="group" aria-label="Period">
          {RANGES.map((n) => (
            <button key={n} type="button" className="seg" aria-pressed={days === n} onClick={() => setDays(n)}>
              {n} days
            </button>
          ))}
        </div>
        {usable.length > 1 && (
          <div className="fsc">
            <label htmlFor="ws">Workspace</label>
            <select id="ws" value={workspace} onChange={(e) => setWorkspace(e.target.value)}>
              {usable.map((w) => (
                <option key={w.slug} value={w.slug}>
                  {w.name}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>
      {query.isError ? (
        <section className="errbox" role="alert">
          <AlertTriangle className="ic" aria-hidden="true" />
          <div>
            <h2>The metrics could not be loaded</h2>
            <p>{query.error.message}</p>
            <button className="btn primary" type="button" onClick={() => query.refetch()}>
              Try again
            </button>
          </div>
        </section>
      ) : !query.data ? (
        <div role="status" aria-busy="true" aria-label="Loading metrics">
          <span className="skel" style={{ height: 260 }} />
        </div>
      ) : query.data.total_leads === 0 ? (
        <section className="empty">
          <h2>No leads in this period</h2>
          <p>Nothing was submitted in the last {days} days. Try a longer period, or wait for the next application.</p>
          <Link className="btn" href="/dashboard">
            Back to leads
          </Link>
        </section>
      ) : (
        <Cards m={query.data} />
      )}
    </>
  );
}

function Cards({ m }: { m: Metrics }) {
  const statusRows = m.by_status.map((s) => ({ ...s, label: statusLabel(s.status) }));
  const scoreRows = m.score_histogram.map((b) => ({
    ...b,
    label: b.max_score === 100 ? "90+" : String(b.min_score),
    range: `${b.min_score} to ${b.max_score}`,
    tier: bucketTier(b.min_score, m.tier_thresholds),
  }));
  const dayRows = m.leads_per_day.map((d) => ({ ...d, label: shortDay(d.day) }));
  const t = m.time_to_qualify;
  const th = m.tier_thresholds;
  const scored = scoredCount(m);
  const tierCount = (tier: string) => m.tier_split.find((x) => x.tier === tier)?.count ?? 0;

  return (
    <div className="stack">
      <ChartCard
        id="m-status"
        headline={statusHeadline(m)}
        caption="Leads by status"
        summary={`Leads by status: ${statusRows.filter((s) => s.count > 0).map((s) => `${s.label} ${s.count}`).join(", ")}.`}
        table={<DataTable head={["Status", "Leads"]} rows={statusRows.map((s) => [s.label, String(s.count)])} />}
      >
        <BarChart
          responsive
          accessibilityLayer={false}
          layout="vertical"
          data={statusRows}
          margin={{ top: 4, right: 36, bottom: 4, left: 0 }}
          style={{ width: "100%", height: statusRows.length * 38 + 8 }}
        >
          <XAxis type="number" hide />
          <YAxis type="category" dataKey="label" width={112} tickLine={false} axisLine={false} tick={AXIS} />
          <Bar dataKey="count" radius={6} barSize={20}>
            {statusRows.map((s) => (
              <Cell key={s.status} fill={STATUS_FILL[s.status]} />
            ))}
            <LabelList dataKey="count" position="right" style={VALUE} />
          </Bar>
        </BarChart>
      </ChartCard>

      <ChartCard
        id="m-score"
        headline={scoreHeadline(m)}
        caption={
          scored === 0
            ? "Score distribution"
            : `Score distribution of ${pluralize(scored, "scored lead")}: ${tierCount("hot")} hot, ${tierCount("warm")} warm, ${tierCount("cold")} cold.${th ? ` Hot starts at ${th.hot_min}, warm at ${th.warm_min}.` : ""}`
        }
        summary={`Score distribution in ten-point groups: ${scoreRows.filter((b) => b.count > 0).map((b) => `${b.range}: ${b.count}`).join(", ") || "no scored leads"}.`}
        table={<DataTable head={["Score", "Leads"]} rows={scoreRows.map((b) => [b.range, String(b.count)])} />}
        legend={
          th && (
            <ul className="legend">
              {(["hot", "warm", "cold"] as const).map((tier) => (
                <li key={tier}>
                  <i style={{ background: TIER_FILL[tier] }} aria-hidden="true" />
                  {tier === "hot" ? `Hot, ${th.hot_min}+` : tier === "warm" ? `Warm, ${th.warm_min} to ${th.hot_min - 1}` : `Cold, below ${th.warm_min}`}
                </li>
              ))}
            </ul>
          )
        }
      >
        <BarChart
          responsive
          accessibilityLayer={false}
          data={scoreRows}
          margin={{ top: 20, right: 4, bottom: 0, left: 0 }}
          style={{ width: "100%", height: 220 }}
        >
          <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--wq-line)" }} tick={AXIS} />
          <YAxis hide allowDecimals={false} />
          <Bar dataKey="count" radius={[6, 6, 0, 0]}>
            {scoreRows.map((b) => (
              <Cell key={b.min_score} fill={TIER_FILL[b.tier]} />
            ))}
            <LabelList dataKey="count" position="top" style={VALUE} formatter={(v: unknown) => (Number(v) > 0 ? String(v) : "")} />
          </Bar>
        </BarChart>
      </ChartCard>

      <ChartCard
        id="m-day"
        headline={timeHeadline(m)}
        caption={`Leads per day${t.p50_seconds !== null && t.p90_seconds !== null ? `. Half were qualified within ${formatDuration(t.p50_seconds)}, nine in ten within ${formatDuration(t.p90_seconds)}.` : ""}`}
        summary={`Leads per day over ${dayRows.length} days, ${m.total_leads} in total; busiest day ${dayRows.reduce((a, b) => (b.count > a.count ? b : a)).label} with ${Math.max(...dayRows.map((d) => d.count))}.`}
        table={<DataTable head={["Day", "Leads"]} rows={dayRows.map((d) => [d.label, String(d.count)])} />}
      >
        <BarChart
          responsive
          accessibilityLayer={false}
          data={dayRows}
          margin={{ top: 8, right: 4, bottom: 0, left: 0 }}
          style={{ width: "100%", height: 200 }}
        >
          <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--wq-line)" }} tick={AXIS} interval="preserveStartEnd" minTickGap={28} />
          <YAxis width={28} allowDecimals={false} tickLine={false} axisLine={false} tick={AXIS} />
          <Bar dataKey="count" fill="var(--wq-plum)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ChartCard>

      <section className="mc" aria-labelledby="m-cost">
        <h2 id="m-cost">{costHeadline(m)}</h2>
        <p className="cap">
          {m.cost.avg_per_lead_usd !== null ? `Average ${formatUsd(m.cost.avg_per_lead_usd)} per lead. ` : ""}
          Spend on these leads: {formatUsd(m.cost.total_usd)}.
        </p>
        <dl className="kv">
          <dt>Model calls</dt>
          <dd className="num">{m.cost.llm_calls}</dd>
          <dt>Provider</dt>
          <dd>{m.cost.providers.length ? m.cost.providers.join(", ") : "none recorded"}</dd>
          <dt>Spent in total</dt>
          <dd className="num">
            {formatUsd(m.cost.lifetime_spent_usd)} of the {formatUsd(m.cost.budget_usd)} budget
          </dd>
        </dl>
        {m.cost.providers.includes("fake") && (
          <p className="muted note">
            The fake provider is a free stand-in for a real model, so this is not a cost estimate.
          </p>
        )}
      </section>
    </div>
  );
}

const AXIS = { fill: "var(--wq-muted)", fontSize: 12 };
const VALUE = { fill: "var(--wq-ink)", fontSize: 12, fontWeight: 600 };

function ChartCard({
  id,
  headline,
  caption,
  summary,
  table,
  legend,
  children,
}: {
  id: string;
  headline: string;
  caption: string;
  summary: string;
  table: ReactNode;
  legend?: ReactNode;
  children: ReactNode;
}) {
  const descId = useId();
  return (
    <section className="mc" aria-labelledby={id}>
      <h2 id={id}>{headline}</h2>
      <p className="cap">{caption}</p>
      <div className="chart" role="img" aria-labelledby={id} aria-describedby={descId}>
        {children}
      </div>
      <p className="sr" id={descId}>
        {summary}
      </p>
      {legend}
      <details className="datatable">
        <summary>View as a table</summary>
        {table}
      </details>
    </section>
  );
}

function DataTable({ head, rows }: { head: [string, string]; rows: string[][] }) {
  return (
    <table className="runlog dt">
      <thead>
        <tr>
          <th scope="col">{head[0]}</th>
          <th scope="col" className="r">
            {head[1]}
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label}>
            <th scope="row">{label}</th>
            <td className="num r">{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
