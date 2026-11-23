import { NextResponse } from "next/server";
import { z } from "zod";
import { errorResponse, handle } from "@/lib/api/bff";
import { metricsSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";

const querySchema = z.object({
  workspace: z.string().regex(/^[a-z0-9][a-z0-9-]{0,63}$/).optional(),
  from: z.iso.date().optional(),
  to: z.iso.date().optional(),
});

export function GET(request: Request) {
  return handle(request, async () => {
    const raw = Object.fromEntries(new URL(request.url).searchParams);
    const parsed = querySchema.safeParse(raw);
    if (!parsed.success) return errorResponse("Bad request", "Invalid workspace or date range.", 400);
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(parsed.data)) if (value) params.set(key, value);
    const query = params.size ? `?${params}` : "";
    return NextResponse.json(await adminFetch(`/admin/metrics${query}`, metricsSchema));
  });
}
