import type { Metadata } from "next";
import { MetricsView } from "@/features/metrics/metrics-view";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Metrics" };

export default async function MetricsPage() {
  const workspaces = await adminFetch("/admin/workspaces", workspaceSummariesSchema);
  const usable = workspaces.filter((w) => w.enabled);
  const defaultWorkspace = (usable.find((w) => !w.draft) ?? usable[0])?.slug ?? "";
  return <MetricsView workspaces={workspaces} defaultWorkspace={defaultWorkspace} />;
}
