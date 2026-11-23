import { NextResponse } from "next/server";
import { assertSameOrigin, errorResponse, handle } from "@/lib/api/bff";
import { kbAskRequestSchema, kbChatEntrySchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { SLUG_PATTERN } from "@/lib/kb/slug";

export const dynamic = "force-dynamic";

// 500 characters at up to 4 bytes each, plus the JSON around them.
const MAX_BODY_BYTES = 2_300;
const tooLarge = () => errorResponse("Payload too large", "The question is too long.", 413);

export function POST(request: Request, ctx: { params: Promise<{ slug: string }> }) {
  return handle(request, async () => {
    const forbidden = assertSameOrigin(request);
    if (forbidden) return forbidden;
    const slug = (await ctx.params).slug;
    if (!SLUG_PATTERN.test(slug)) return errorResponse("Not found", "Unknown workspace.", 404);

    if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY_BYTES) return tooLarge();
    const text = await request.text();
    if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) return tooLarge();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      return errorResponse("Bad request", "The request body must be JSON.", 400);
    }
    const parsed = kbAskRequestSchema.safeParse(json);
    if (!parsed.success) {
      return errorResponse("Validation failed", "Ask a question of 3 to 500 characters.", 400);
    }
    const entry = await adminFetch(`/admin/kb/${slug}/ask`, kbChatEntrySchema, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed.data),
    });
    return NextResponse.json(entry);
  });
}
