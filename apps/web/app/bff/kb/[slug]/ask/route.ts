import { NextResponse } from "next/server";
import { readBoundedText } from "@/lib/api/bounded-body";
import { assertSameOrigin, errorResponse, handle } from "@/lib/api/bff";
import { kbAskRequestSchema, kbChatEntrySchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { SLUG_PATTERN } from "@/lib/kb/slug";
import { demoRateLimit } from "@/lib/public-demo";

export const dynamic = "force-dynamic";

// 500 characters at up to 4 bytes each, plus the JSON around them. The declared Content-Length is
// refused first; the body is then read in a bounded stream, so a chunked upload without a
// Content-Length is cut off at the limit as well.
const MAX_BODY_BYTES = 2_300;
const tooLarge = () => errorResponse("Payload too large", "The question is too long.", 413);

export function POST(request: Request, ctx: { params: Promise<{ slug: string }> }) {
  return handle(request, async () => {
    const forbidden = assertSameOrigin(request);
    if (forbidden) return forbidden;
    const limited = demoRateLimit(request, "ask");
    if (limited) return limited;
    const slug = (await ctx.params).slug;
    if (!SLUG_PATTERN.test(slug)) return errorResponse("Not found", "Unknown workspace.", 404);

    const text = await readBoundedText(request, MAX_BODY_BYTES);
    if (text === null) return tooLarge();
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
