import type { Metadata } from "next";
import { AppHeader } from "@/components/app-nav";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Leads" };

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const workspaces = await adminFetch("/admin/workspaces", workspaceSummariesSchema).catch(() => []);
  const first = workspaces.find((w) => w.enabled && !w.draft);
  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <AppHeader applyHref={first ? `/w/${first.slug}/apply` : null} />
      <main id="main">{children}</main>
    </div>
  );
}
