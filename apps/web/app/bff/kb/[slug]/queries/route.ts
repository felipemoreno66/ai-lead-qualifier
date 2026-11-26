import { NextResponse } from "next/server";
import { errorResponse, handle } from "@/lib/api/bff";
import { kbChatEntriesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { demoReadLimit } from "@/lib/public-demo";
import { hideInvisibleWorkspace } from "@/lib/workspaces";
import { SLUG_PATTERN } from "@/lib/kb/slug";

export const dynamic = "force-dynamic";

export function GET(request: Request, ctx: { params: Promise<{ slug: string }> }) {
  return handle(request, async () => {
    const slug = (await ctx.params).slug;
    if (!SLUG_PATTERN.test(slug)) return errorResponse("Not found", "Unknown workspace.", 404);
    const limited = demoReadLimit(request, "costly");
    if (limited) return limited;
    const hidden = await hideInvisibleWorkspace(slug);
    if (hidden) return hidden;
    return NextResponse.json(
      await adminFetch(`/admin/kb/${slug}/queries?limit=10`, kbChatEntriesSchema),
    );
  });
}
