import { NextResponse } from "next/server";
import { z } from "zod";
import { assertSameOrigin, errorResponse, handle } from "@/lib/api/bff";
import { retriggerResultSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";

export function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  return handle(async () => {
    const forbidden = assertSameOrigin(request);
    if (forbidden) return forbidden;
    const id = z.uuid().safeParse((await ctx.params).id);
    if (!id.success) return errorResponse("Not found", "Unknown lead.", 404);
    const result = await adminFetch(`/admin/leads/${id.data}/retrigger`, retriggerResultSchema, {
      method: "POST",
    });
    return NextResponse.json(result, { status: 202 });
  });
}
