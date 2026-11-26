import { NextResponse } from "next/server";
import { handle } from "@/lib/api/bff";
import { visibleWorkspaces } from "@/lib/workspaces";

export const dynamic = "force-dynamic";

export function GET(request: Request) {
  return handle(request, async () => NextResponse.json(await visibleWorkspaces()));
}
