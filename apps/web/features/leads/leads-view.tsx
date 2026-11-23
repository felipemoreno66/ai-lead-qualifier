"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { AlertTriangle, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ScoreCell, StatusBadge, TierLabel } from "@/components/status-badge";
import type { LeadListItem, WorkspaceSummary } from "@/lib/api/schemas";
import { countryName, formatDateTime, pluralize, STATUS_LABELS } from "@/lib/format";
import {
  hasActiveFilters,
  PAGE_SIZE,
  parseFilters,
  queryKey,
  SCORE_BANDS,
  STATUSES,
  toUrlParams,
  type LeadFilters,
  type ScoreBand,
} from "@/lib/leads/filters";
import { fetchLeads } from "./queries";

const GROUPS = {
  attention: { title: "Needs attention", hint: "Something failed. Retry to continue." },
  hot: { title: "Hot", hint: "Reply today. Scores 75 and above." },
  warm: { title: "Warm", hint: "Reply this week. Scores 45 to 74." },
  scoring: { title: "Not scored yet", hint: "These leads are waiting for a score." },
  cold: { title: "Cold", hint: "Low fit. Scores below 45." },
} as const;

type Props = { workspaces: WorkspaceSummary[]; defaultWorkspace: string };

export function LeadsView({ workspaces, defaultWorkspace }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = useMemo(() => {
    const parsed = parseFilters(searchParams);
    return { ...parsed, workspace: parsed.workspace ?? defaultWorkspace };
  }, [searchParams, defaultWorkspace]);

  const [search, setSearch] = useState(filters.q);
  const lastQ = useRef(filters.q);
  useEffect(() => {
    if (filters.q !== lastQ.current) {
      lastQ.current = filters.q;
      setSearch(filters.q);
    }
  }, [filters.q]);

  const update = (next: Partial<LeadFilters>) => {
    const merged = { ...filters, page: 1, ...next };
    const params = toUrlParams(merged);
    router.replace(params.size ? `${pathname}?${params}` : pathname, { scroll: false });
  };

  useEffect(() => {
    if (search.trim() === filters.q.trim()) return;
    const timer = setTimeout(() => {
      lastQ.current = search;
      update({ q: search });
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const query = useQuery({
    queryKey: queryKey(filters),
    queryFn: () => fetchLeads(filters),
    placeholderData: keepPreviousData,
  });

  const workspace = workspaces.find((w) => w.slug === filters.workspace);
  const enabled = workspaces.filter((w) => w.enabled);
  const toggleStatus = (status: (typeof STATUSES)[number]) =>
    update({
      statuses: filters.statuses.includes(status)
        ? filters.statuses.filter((s) => s !== status)
        : [...filters.statuses, status],
    });

  const data = query.data;
  return (
    <>
      <div className="page-h">
        <h1>Who should you reply to first?</h1>
        <p className="muted" aria-live="polite">
          {data
            ? `${pluralize(data.total, "lead")}${workspace ? ` in ${workspace.name}` : ""}${hasActiveFilters(filters) ? " match the filters" : ""}.`
            : "Loading leads."}
        </p>
      </div>

      <form className="filters" aria-label="Filter leads" onSubmit={(e) => e.preventDefault()}>
        <div className="segs" role="group" aria-label="Status">
          <button
            type="button"
            className="seg"
            aria-pressed={filters.statuses.length === 0}
            onClick={() => update({ statuses: [] })}
          >
            All
          </button>
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              className="seg"
              aria-pressed={filters.statuses.includes(s)}
              onClick={() => toggleStatus(s)}
            >
              {STATUS_LABELS[s]}
            </button>
          ))}
        </div>
        <div className="fsc">
          <label htmlFor="score">Score</label>
          <select
            id="score"
            value={filters.band}
            onChange={(e) => update({ band: e.target.value as ScoreBand })}
          >
            {Object.entries(SCORE_BANDS).map(([key, band]) => (
              <option key={key} value={key}>
                {band.label}
              </option>
            ))}
          </select>
        </div>
        <div className="fsc">
          <label htmlFor="q" className="sr">
            Search by name or email
          </label>
          <Search className="ic" aria-hidden="true" />
          <input
            id="q"
            type="search"
            placeholder="Search name or email"
            value={search}
            maxLength={100}
            onChange={(e) => setSearch(e.target.value)}
            style={{ minHeight: 44, width: 240 }}
          />
        </div>
        {enabled.length > 1 && (
          <div className="fsc">
            <label htmlFor="workspace">Workspace</label>
            <select
              id="workspace"
              value={filters.workspace}
              onChange={(e) => update({ workspace: e.target.value })}
            >
              {enabled.map((w) => (
                <option key={w.slug} value={w.slug}>
                  {w.name}
                  {w.draft ? " (draft)" : ""}
                </option>
              ))}
            </select>
          </div>
        )}
      </form>

      {query.isError && !data ? (
        <ErrorState message={query.error.message} onRetry={() => query.refetch()} />
      ) : !data ? (
        <LoadingState />
      ) : data.items.length === 0 ? (
        <EmptyState
          filtered={hasActiveFilters(filters)}
          applySlug={workspace && !workspace.draft ? workspace.slug : null}
          onClear={() => update({ statuses: [], band: "any", q: "" })}
        />
      ) : (
        <div aria-busy={query.isFetching}>
          <GroupedLeads items={data.items} />
          <Pager
            page={data.page}
            total={data.total}
            onPage={(page) => update({ page })}
            pending={query.isFetching}
          />
        </div>
      )}
    </>
  );
}

function GroupedLeads({ items }: { items: LeadListItem[] }) {
  const groups: { key: keyof typeof GROUPS; rows: LeadListItem[] }[] = [];
  for (const item of items) {
    const last = groups.at(-1);
    if (last && last.key === item.group) last.rows.push(item);
    else groups.push({ key: item.group, rows: [item] });
  }
  return (
    <>
      {groups.map(({ key, rows }, i) => (
        <section className="grp" aria-labelledby={`g-${key}-${i}`} key={`${key}-${i}`}>
          <div className="grp-h">
            <h2 id={`g-${key}-${i}`}>{GROUPS[key].title}</h2>
            <p>{GROUPS[key].hint}</p>
          </div>
          <table className="leads">
            <thead>
              <tr>
                <th scope="col">Lead</th>
                <th scope="col">Status</th>
                <th scope="col">Score</th>
                <th scope="col">Tier</th>
                <th scope="col">Program</th>
                <th scope="col">Country</th>
                <th scope="col">Created</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((lead) => (
                <tr key={lead.id}>
                  <th scope="row" data-label="Lead">
                    <Link href={`/dashboard/leads/${lead.id}`}>{lead.name}</Link>
                  </th>
                  <td data-label="Status">
                    <StatusBadge status={lead.status} />
                  </td>
                  <td data-label="Score">
                    <ScoreCell score={lead.score} />
                  </td>
                  <td data-label="Tier">
                    <TierLabel tier={lead.tier} />
                  </td>
                  <td data-label="Program">{lead.interest ?? "Not specified"}</td>
                  <td data-label="Country">{countryName(lead.country)}</td>
                  <td className="num" data-label="Created">
                    <time dateTime={lead.created_at}>{formatDateTime(lead.created_at)}</time>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </>
  );
}

function Pager({
  page,
  total,
  onPage,
  pending,
}: {
  page: number;
  total: number;
  onPage: (page: number) => void;
  pending: boolean;
}) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pages === 1) return null;
  return (
    <nav className="pager" aria-label="Pagination">
      <button className="btn" type="button" disabled={page <= 1 || pending} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="num muted">
        Page {page} of {pages}
      </span>
      <button className="btn" type="button" disabled={page >= pages || pending} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

function LoadingState() {
  return (
    <div aria-busy="true" aria-label="Loading leads" role="status" style={{ marginTop: 44 }}>
      {[0, 1, 2, 3].map((i) => (
        <span className="skel" key={i} style={{ height: 56, marginBottom: 14 }} />
      ))}
    </div>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <section className="errbox" role="alert" style={{ marginTop: 44 }}>
      <AlertTriangle className="ic" aria-hidden="true" />
      <div>
        <h2>The leads could not be loaded</h2>
        <p>{message}. Check that the agent service is running, then try again.</p>
        <button className="btn primary" type="button" onClick={onRetry}>
          Try again
        </button>
      </div>
    </section>
  );
}

function EmptyState({
  filtered,
  applySlug,
  onClear,
}: {
  filtered: boolean;
  applySlug: string | null;
  onClear: () => void;
}) {
  return (
    <section className="empty">
      <h2>{filtered ? "Nothing here yet" : "No leads yet"}</h2>
      {filtered ? (
        <>
          <p>No leads match these filters. Clear them to see every lead.</p>
          <button className="btn" type="button" onClick={onClear}>
            Clear filters
          </button>
        </>
      ) : (
        <>
          <p>New applications appear here as soon as someone submits the form.</p>
          {applySlug && (
            <Link className="btn" href={`/w/${applySlug}/apply`}>
              Open the application form
            </Link>
          )}
        </>
      )}
    </section>
  );
}
