import { NextResponse } from "next/server";
import { z } from "zod";
import { assertSameOrigin, errorResponse, handle } from "@/lib/api/bff";
import { leadDetailSchema } from "@/lib/api/schemas";
import { adminCall, adminFetch } from "@/lib/api/server";
import { demoForbidden } from "@/lib/public-demo";

export const dynamic = "force-dynamic";
type Ctx = { params: Promise<{ id: string }> };

async function leadId(ctx: Ctx): Promise<string | null> {
  const parsed = z.uuid().safeParse((await ctx.params).id);
  return parsed.success ? parsed.data : null;
}

export function GET(request: Request, ctx: Ctx) {
  return handle(request, async () => {
    const id = await leadId(ctx);
    if (!id) return errorResponse("Not found", "Unknown lead.", 404);
    return NextResponse.json(await adminFetch(`/admin/leads/${id}`, leadDetailSchema));
  });
}

export function DELETE(request: Request, ctx: Ctx) {
  return handle(request, async () => {
    const forbidden = assertSameOrigin(request);
    if (forbidden) return forbidden;
    const disabled = demoForbidden("Deleting leads");
    if (disabled) return disabled;
    const id = await leadId(ctx);
    if (!id) return errorResponse("Not found", "Unknown lead.", 404);
    await adminCall(`/admin/leads/${id}`, { method: "DELETE" });
    return new Response(null, { status: 204 });
  });
}
