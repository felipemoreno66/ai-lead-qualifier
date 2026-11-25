import type { Metadata } from "next";
import Link from "next/link";
import { AskView } from "@/features/kb/ask-view";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Ask the docs" };

export default async function AskPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = (await searchParams).workspace;
  const wanted = Array.isArray(raw) ? raw[0] : raw;
  const workspaces = (await adminFetch("/admin/workspaces", workspaceSummariesSchema)).filter(
    (w) => w.enabled,
  );
  const current = workspaces.find((w) => w.slug === wanted) ?? workspaces.find((w) => !w.draft) ?? workspaces[0];
  if (!current) {
    return (
      <div className="page-h">
        <h1>Ask the docs</h1>
        <p className="muted">No workspace is enabled, so there are no documents to ask.</p>
      </div>
    );
  }
  return (
    <>
      {workspaces.length > 1 && (
        <nav className="wsnav" aria-label="Workspace">
          {workspaces.map((w) => (
            <Link
              key={w.slug}
              href={`/dashboard/ask?workspace=${w.slug}`}
              aria-current={w.slug === current.slug ? "page" : undefined}
            >
              {w.name}
            </Link>
          ))}
        </nav>
      )}
      <AskView key={current.slug} slug={current.slug} workspaceName={current.name} />
    </>
  );
}
