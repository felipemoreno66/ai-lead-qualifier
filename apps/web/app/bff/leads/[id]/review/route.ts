import { NextResponse } from "next/server";
import { z } from "zod";
import { assertSameOrigin, errorResponse, handle } from "@/lib/api/bff";
import { reviewRequestSchema, reviewResultSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";

// Whole request bodies above this size are refused before parsing (the longest field is 4,000 chars).
const MAX_BODY_BYTES = 32_000;

export function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  return handle(request, async () => {
    const forbidden = assertSameOrigin(request);
    if (forbidden) return forbidden;
    const id = z.uuid().safeParse((await ctx.params).id);
    if (!id.success) return errorResponse("Not found", "Unknown lead.", 404);

    const text = await request.text();
    if (text.length > MAX_BODY_BYTES) return errorResponse("Payload too large", "The request is too large.", 413);
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      return errorResponse("Bad request", "The request body must be JSON.", 400);
    }
    const parsed = reviewRequestSchema.safeParse(json);
    if (!parsed.success) {
      return errorResponse("Validation failed", "The review request is not valid.", 400);
    }
    if (parsed.data.action === "edit" && !parsed.data.body) {
      return errorResponse("Validation failed", "An edit needs the new message text.", 400);
    }
    // Only the validated, stripped fields are forwarded.
    const result = await adminFetch(`/admin/leads/${id.data}/review`, reviewResultSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed.data),
    });
    return NextResponse.json(result);
  });
}
