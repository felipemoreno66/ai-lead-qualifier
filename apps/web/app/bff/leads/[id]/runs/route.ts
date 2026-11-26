import { NextResponse } from "next/server";
import { z } from "zod";
import { errorResponse, handle } from "@/lib/api/bff";
import { agentRunsSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { demoReadLimit } from "@/lib/public-demo";

export const dynamic = "force-dynamic";

export function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  return handle(request, async () => {
    const limited = demoReadLimit(request, "costly");
    if (limited) return limited;
    const id = z.uuid().safeParse((await ctx.params).id);
    if (!id.success) return errorResponse("Not found", "Unknown lead.", 404);
    return NextResponse.json(await adminFetch(`/admin/leads/${id.data}/runs`, agentRunsSchema));
  });
}
