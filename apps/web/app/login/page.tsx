import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { PublicShell } from "@/components/public-shell";
import { LoginForm } from "@/features/auth/login-form";
import { authMode, safeNext, UNCONFIGURED_MESSAGE } from "@/lib/auth/mode";
import { authEnv, hasSession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Sign in", robots: { index: false } };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const next = safeNext((await searchParams).next);
  const mode = authMode(authEnv());
  if (mode === "off") redirect("/dashboard");
  if (mode === "session" && (await hasSession(await headers()))) redirect(next);
  return (
    <PublicShell name="Lead Qualifier">
      <div className="apply">
        <div className="intro">
          <h1>Sign in</h1>
          <p className="lead">The dashboard is private. Use the operator account for this instance.</p>
        </div>
        {mode === "unconfigured" ? (
          <p className="form-alert" role="alert">
            {UNCONFIGURED_MESSAGE}
          </p>
        ) : (
          <LoginForm next={next} />
        )}
      </div>
    </PublicShell>
  );
}
