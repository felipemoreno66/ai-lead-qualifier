import { dehydrate, HydrationBoundary, QueryClient } from "@tanstack/react-query";
import { LeadsView } from "@/features/leads/leads-view";
import { visibleWorkspaces } from "@/lib/workspaces";
import { leadListSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { parseFilters, queryKey, toApiParams } from "@/lib/leads/filters";

export const dynamic = "force-dynamic";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const workspaces = await visibleWorkspaces();
  const usable = workspaces.filter((w) => w.enabled);
  const defaultWorkspace = (usable.find((w) => !w.draft) ?? usable[0])?.slug ?? "";

  const url = new URLSearchParams();
  for (const [key, value] of Object.entries(raw))
    for (const v of Array.isArray(value) ? value : value === undefined ? [] : [value]) url.append(key, v);
  const parsed = parseFilters(url);
  const filters = { ...parsed, workspace: parsed.workspace ?? defaultWorkspace };

  const client = new QueryClient();
  await client
    .prefetchQuery({
      queryKey: queryKey(filters),
      queryFn: () => adminFetch(`/admin/leads?${toApiParams(filters)}`, leadListSchema),
    })
    .catch(() => undefined);

  return (
    <HydrationBoundary state={dehydrate(client)}>
      <LeadsView workspaces={workspaces} defaultWorkspace={defaultWorkspace} />
    </HydrationBoundary>
  );
}
