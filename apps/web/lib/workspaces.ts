import "server-only";
import { errorResponse } from "@/lib/api/bff";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import type { z } from "zod";
import { adminFetch } from "@/lib/api/server";
import { isPublicDemo } from "@/lib/public-demo-flag";

/**
 * Workspaces the dashboard may show. In the public demo only enabled, non-draft workspaces are
 * visible (a defense in depth: the agent only loads the enabled ones). Elsewhere: all of them.
 */
type WorkspaceSummary = z.infer<typeof workspaceSummariesSchema>[number];
const CACHE_MS = 30_000;
let cached: { at: number; list: WorkspaceSummary[] } | null = null;

/** Test hook. */
export function resetWorkspaceCache(): void {
  cached = null;
}

export async function visibleWorkspaces(now = Date.now()): Promise<WorkspaceSummary[]> {
  if (!isPublicDemo()) return adminFetch("/admin/workspaces", workspaceSummariesSchema);
  // Public demo: slug checks run on every request, so the list is cached briefly.
  if (cached && now - cached.at < CACHE_MS) return cached.list;
  const all = await adminFetch("/admin/workspaces", workspaceSummariesSchema);
  cached = { at: now, list: all.filter((w) => w.enabled && !w.draft) };
  return cached.list;
}

export async function isVisibleWorkspace(slug: string): Promise<boolean> {
  if (!isPublicDemo()) return true;
  return (await visibleWorkspaces()).some((w) => w.slug === slug);
}

/** 404 response when `slug` is not visible in the public demo, else null. */
export async function hideInvisibleWorkspace(slug: string | undefined): Promise<Response | null> {
  if (!slug || (await isVisibleWorkspace(slug))) return null;
  return errorResponse("Not found", "Unknown workspace.", 404);
}
