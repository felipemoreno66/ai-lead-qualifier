import { NextResponse } from "next/server";
import { handle } from "@/lib/api/bff";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { isPublicDemo } from "@/lib/public-demo";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return handle(request, async () => {
    const all = await adminFetch("/admin/workspaces", workspaceSummariesSchema);
    // The public demo shows only the workspaces that are switched on (no drafts or disabled ones).
    return NextResponse.json(isPublicDemo() ? all.filter((w) => w.enabled && !w.draft) : all);
  });
}
