import "server-only";
import { errorResponse } from "@/lib/api/bff";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { isPublicDemo } from "@/lib/public-demo-flag";

/**
 * Workspaces the dashboard may show. In the public demo only enabled, non-draft workspaces are
 * visible (a defense in depth: the agent only loads the enabled ones). Elsewhere: all of them.
 */
export async function visibleWorkspaces() {
  const all = await adminFetch("/admin/workspaces", workspaceSummariesSchema);
  return isPublicDemo() ? all.filter((w) => w.enabled && !w.draft) : all;
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
