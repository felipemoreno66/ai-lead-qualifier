"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useId, useState, type ReactNode } from "react";
import { Bar, BarChart, Cell, LabelList, XAxis, YAxis } from "recharts";
import type { Metrics, WorkspaceSummary } from "@/lib/api/schemas";
import { pluralize } from "@/lib/format";
import {
  costHeadline,
  dayTicks,
  formatDuration,
  formatUsd,
  rangeFor,
  RANGES,
  scoreHeadline,
  scoredCount,
  shortDay,
  statusHeadline,
  statusLabel,
  timeCaption,
  timeHeadline,
  volumeHeadline,
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
  const [allDays, setAllDays] = useState(false);
  const statusRows = m.by_status.map((s) => ({ ...s, label: statusLabel(s.status) }));
  const scoreRows = m.score_histogram.map((b) => ({
    ...b,
    label: String(b.min_score),
    range: `${b.min_score} to ${b.max_score}`,
  }));
  const dayRows = m.leads_per_day.map((d) => ({ ...d, label: shortDay(d.day) }));
  const busiest = dayRows.reduce((a, b) => (b.count > a.count ? b : a));
  const t = m.time_to_qualify;
  const th = m.tier_thresholds;
  const scored = scoredCount(m);

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
          <Bar dataKey="count" radius={6} barSize={20} minPointSize={2}>
            {statusRows.map((s) => (
              <Cell key={s.status} fill={STATUS_FILL[s.status]} />
            ))}
            <LabelList dataKey="count" position="right" style={VALUE} formatter={(v: unknown) => String(v)} />
          </Bar>
        </BarChart>
      </ChartCard>

      <ChartCard
        id="m-score"
        headline={scoreHeadline(m)}
        caption={
          scored === 0
            ? "Score distribution"
            : `Score distribution of ${pluralize(scored, "scored lead")}, in ten-point groups. The group's first score is on the axis.`
        }
        summary={`Score distribution in ten-point groups: ${scoreRows.filter((b) => b.count > 0).map((b) => `${b.range}: ${b.count} (${b.hot} hot, ${b.warm} warm, ${b.cold} cold)`).join("; ") || "no scored leads"}.`}
        table={
          <DataTable
            head={["Score", "Leads"]}
            rows={scoreRows.filter((b) => b.count > 0).map((b) => [b.range, `${b.count} (${b.hot} hot, ${b.warm} warm, ${b.cold} cold)`])}
          />
        }
        legend={
          <ul className="legend">
            {(["hot", "warm", "cold"] as const).map((tier) => (
              <li key={tier}>
                <i style={{ background: TIER_FILL[tier] }} aria-hidden="true" />
                {th
                  ? tier === "hot"
                    ? `Hot, ${th.hot_min} and above`
                    : tier === "warm"
                      ? `Warm, ${th.warm_min} to ${th.hot_min - 1}`
                      : `Cold, below ${th.warm_min}`
                  : tier[0].toUpperCase() + tier.slice(1)}
              </li>
            ))}
          </ul>
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
          <Bar dataKey="cold" stackId="s" fill={TIER_FILL.cold} />
          <Bar dataKey="warm" stackId="s" fill={TIER_FILL.warm} />
          <Bar dataKey="hot" stackId="s" fill={TIER_FILL.hot} radius={[6, 6, 0, 0]}>
            <LabelList dataKey="count" position="top" style={VALUE} formatter={(v: unknown) => (Number(v) > 0 ? String(v) : "")} />
          </Bar>
        </BarChart>
      </ChartCard>

      <ChartCard
        id="m-day"
        wide
        headline={volumeHeadline(m)}
        caption="Leads per day (UTC)"
        summary={`Leads per day over ${dayRows.length} days, ${m.total_leads} in total; busiest day ${busiest.label} with ${busiest.count}.`}
        table={
          <>
            <DataTable
              head={["Day", "Leads"]}
              rows={(allDays ? dayRows : dayRows.filter((d) => d.count > 0)).map((d) => [d.label, String(d.count)])}
            />
            <button className="btn linkish" type="button" aria-pressed={allDays} onClick={() => setAllDays((v) => !v)}>
              {allDays ? "Show only days with leads" : "Show all days"}
            </button>
          </>
        }
      >
        <BarChart
          responsive
          accessibilityLayer={false}
          data={dayRows}
          margin={{ top: 8, right: 4, bottom: 0, left: 0 }}
          style={{ width: "100%", height: 200 }}
        >
          <XAxis dataKey="label" ticks={dayTicks(dayRows.map((d) => d.label))} interval={0} tickLine={false} axisLine={{ stroke: "var(--wq-line)" }} tick={AXIS} />
          <YAxis width={28} allowDecimals={false} tickLine={false} axisLine={false} tick={AXIS} />
          <Bar dataKey="count" fill="var(--wq-plum)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ChartCard>

      <section className="mc" aria-labelledby="m-time">
        <h2 id="m-time">{timeHeadline(m)}</h2>
        <p className="cap">{timeCaption(m)}</p>
        {t.count > 0 && t.p50_seconds !== null && t.p90_seconds !== null && t.avg_seconds !== null && (
          <dl className="kv">
            <dt>Median</dt>
            <dd className="num">{formatDuration(t.p50_seconds)}</dd>
            <dt>90th percentile</dt>
            <dd className="num">{formatDuration(t.p90_seconds)}</dd>
            <dt>Average</dt>
            <dd className="num">{formatDuration(t.avg_seconds)}</dd>
          </dl>
        )}
      </section>

      <section className="mc" aria-labelledby="m-cost">
        <h2 id="m-cost">{costHeadline(m)}</h2>
        <p className="cap">
          {m.cost.avg_per_lead_usd !== null ? `Average ${formatUsd(m.cost.avg_per_lead_usd)} per lead. ` : ""}
          Spend on these leads: {formatUsd(m.cost.total_usd)}. Questions asked in Ask the docs are counted separately below.
        </p>
        <dl className="kv">
          <dt>Model calls</dt>
          <dd className="num">{m.cost.llm_calls}</dd>
          <dt>Provider</dt>
          <dd>{m.cost.providers.length ? m.cost.providers.join(", ") : "none recorded"}</dd>
          <dt>Ask the docs</dt>
          <dd className="num">
            {pluralize(m.cost.ask_questions, "question")}, {formatUsd(m.cost.ask_total_usd)}
          </dd>
          <dt>Spent in total</dt>
          <dd className="num">
            {formatUsd(m.cost.lifetime_spent_usd)} of the {formatUsd(m.cost.budget_usd)} budget
          </dd>
        </dl>
        <p className="muted note">
          The total for these leads leaves out leads that were deleted; the lifetime figure still
          counts them.
          {m.cost.providers.includes("fake") && " The fake provider is a free stand-in for a real model, so this is not a cost estimate."}
        </p>
      </section>
    </div>
  );
}

const AXIS = { fill: "var(--wq-muted)", fontSize: 12 };
const VALUE = { fill: "var(--wq-ink)", fontSize: 12, fontWeight: 600 };

function ChartCard({
  id,
  wide,
  headline,
  caption,
  summary,
  table,
  legend,
  children,
}: {
  id: string;
  wide?: boolean;
  headline: string;
  caption: string;
  summary: string;
  table: ReactNode;
  legend?: ReactNode;
  children: ReactNode;
}) {
  const descId = useId();
  return (
    <section className={`mc${wide ? " wide" : ""}`} aria-labelledby={id}>
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
    <table className="dt">
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
