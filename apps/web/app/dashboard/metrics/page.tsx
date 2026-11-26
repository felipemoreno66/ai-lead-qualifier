import type { Metadata } from "next";
import { MetricsView } from "@/features/metrics/metrics-view";
import { visibleWorkspaces } from "@/lib/workspaces";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Metrics" };

export default async function MetricsPage() {
  const workspaces = await visibleWorkspaces();
  const usable = workspaces.filter((w) => w.enabled);
  const defaultWorkspace = (usable.find((w) => !w.draft) ?? usable[0])?.slug ?? "";
  return <MetricsView workspaces={workspaces} defaultWorkspace={defaultWorkspace} />;
}
