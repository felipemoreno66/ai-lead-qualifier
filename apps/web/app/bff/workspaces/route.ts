import { NextResponse } from "next/server";
import { handle } from "@/lib/api/bff";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return handle(request, async () =>
    NextResponse.json(await adminFetch("/admin/workspaces", workspaceSummariesSchema)),
  );
}
