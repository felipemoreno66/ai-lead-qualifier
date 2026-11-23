import type { Metadata } from "next";
import { headers } from "next/headers";
import { authState } from "@/lib/auth/dashboard-guard";
import { AppHeader } from "@/components/app-nav";
import { workspaceSummariesSchema } from "@/lib/api/schemas";
import { adminFetch } from "@/lib/api/server";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Leads" };

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  // Defense in depth: the proxy already guards this route, the layout refuses to render without it.
  const state = authState((await headers()).get("authorization"), {
    APP_ENV: process.env.APP_ENV,
    DASHBOARD_USER: process.env.DASHBOARD_USER,
    DASHBOARD_PASSWORD: process.env.DASHBOARD_PASSWORD,
  });
  if (state === "unconfigured" || state === "denied") {
    return (
      <main id="main">
        <h1>Dashboard unavailable</h1>
        <p>Operator authentication is required.</p>
      </main>
    );
  }
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
