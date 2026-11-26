import type { Metadata } from "next";
import { headers } from "next/headers";
import { authMode } from "@/lib/auth/mode";
import { authEnv, hasSession } from "@/lib/auth/session";
import { AppHeader } from "@/components/app-nav";
import { instanceStatusSchema } from "@/lib/api/schemas";
import { visibleWorkspaces } from "@/lib/workspaces";
import { adminFetch } from "@/lib/api/server";
import { isPublicDemo } from "@/lib/public-demo-flag";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Leads" };

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  // Defense in depth: the proxy already guards this route, the layout refuses to render without it.
  const mode = authMode(authEnv());
  if (mode === "unconfigured" || (mode === "session" && !(await hasSession(await headers())))) {
    return (
      <main id="main">
        <h1>Dashboard unavailable</h1>
        <p>Operator authentication is required.</p>
      </main>
    );
  }
  const workspaces = await visibleWorkspaces().catch(() => []);
  const status = await adminFetch("/admin/status", instanceStatusSchema).catch(() => null);
  const first = workspaces.find((w) => w.enabled && !w.draft);
  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      {status?.demo_mode && !isPublicDemo() && (
        <p className="demo-bar" role="note">
          <b>Demo mode</b>
          <span>Sample data and a deterministic stand-in model, no real AI calls.</span>
        </p>
      )}
      <AppHeader applyHref={first ? `/w/${first.slug}/apply` : null} showSignOut={mode === "session"} />
      <main id="main">{children}</main>
    </div>
  );
}
