import { NextResponse, type NextRequest } from "next/server";
import { z } from "zod";
import { errorResponse, handle } from "@/lib/api/bff";
import { leadListSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";
import { DEMO_MAX_PAGE_SIZE, demoReadLimit, isPublicDemo } from "@/lib/public-demo";
import { hideInvisibleWorkspace } from "@/lib/workspaces";
import { STATUSES, TIERS } from "@/lib/leads/filters";

export const dynamic = "force-dynamic";

const csv = <T extends readonly [string, ...string[]]>(values: T) =>
  z
    .string()
    .optional()
    .transform((v) => (v ? v.split(",") : []))
    .pipe(z.array(z.enum(values)));

const querySchema = z.object({
  workspace: z.string().regex(/^[a-z0-9-]+$/).max(60).optional(),
  status: csv(STATUSES),
  tier: csv(TIERS),
  score_min: z.coerce.number().int().min(0).max(100).optional(),
  score_max: z.coerce.number().int().min(0).max(100).optional(),
  q: z.string().max(100).optional(),
  sort: z.enum(["priority", "-created_at", "created_at", "-score", "score", "name", "-name"]).optional(),
  page: z.coerce.number().int().min(1).default(1),
  page_size: z.coerce.number().int().min(1).max(100).default(25),
});

export function GET(request: NextRequest) {
  return handle(request, async () => {
    const parsed = querySchema.safeParse(Object.fromEntries(request.nextUrl.searchParams));
    if (!parsed.success) return errorResponse("Invalid query", parsed.error.issues[0]?.message ?? "", 400);
    const hidden = await hideInvisibleWorkspace(parsed.data.workspace);
    if (hidden) return hidden;
    // Searches and big pages are the costly reads; plain list views are not counted.
    if (parsed.data.q || parsed.data.page_size > 10) {
      const limited = demoReadLimit(request);
      if (limited) return limited;
    }
    const { status, tier, ...rest } = parsed.data;
    if (isPublicDemo()) rest.page_size = Math.min(rest.page_size, DEMO_MAX_PAGE_SIZE);
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(rest)) if (value !== undefined) params.set(key, String(value));
    if (status.length) params.set("status", status.join(","));
    if (tier.length) params.set("tier", tier.join(","));
    return NextResponse.json(await adminFetch(`/admin/leads?${params}`, leadListSchema));
  });
}
