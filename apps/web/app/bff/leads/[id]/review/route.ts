import { NextResponse } from "next/server";
import { z } from "zod";
import { assertSameOrigin, errorResponse, handle } from "@/lib/api/bff";
import { reviewRequestSchema, reviewResultSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { demoRateLimit } from "@/lib/public-demo";

export const dynamic = "force-dynamic";

// Bodies above this many bytes are refused (the longest field is 4,000 characters, up to 4 bytes each).
const MAX_BODY_BYTES = 24_000;
const tooLarge = () => errorResponse("Payload too large", "The request is too large.", 413);

export function POST(request: Request, ctx: { params: Promise<{ id: string }> }) {
  return handle(request, async () => {
    const forbidden = assertSameOrigin(request);
    if (forbidden) return forbidden;
    const limited = demoRateLimit(request, "review");
    if (limited) return limited;
    const id = z.uuid().safeParse((await ctx.params).id);
    if (!id.success) return errorResponse("Not found", "Unknown lead.", 404);

    // Refuse on the declared size before reading anything, then on the real UTF-8 size.
    if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY_BYTES) return tooLarge();
    const text = await request.text();
    if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) return tooLarge();
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
    // Only the validated, stripped fields are forwarded.
    const result = await adminFetch(`/admin/leads/${id.data}/review`, reviewResultSchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed.data),
    });
    return NextResponse.json(result);
  });
}
