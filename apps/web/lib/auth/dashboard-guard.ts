import { createHash, timingSafeEqual } from "node:crypto";

export type GuardEnv = {
  APP_ENV?: string;
  DASHBOARD_USER?: string;
  DASHBOARD_PASSWORD?: string;
};

export function isProtectedPath(pathname: string): boolean {
  return /^\/(dashboard|bff)(\/|$)/.test(pathname);
}

const digest = (value: string) => createHash("sha256").update(value).digest();
const equal = (a: string, b: string) => timingSafeEqual(digest(a), digest(b));

function credentialsFrom(header: string | null): { user: string; password: string } | null {
  const [scheme, encoded] = (header ?? "").split(" ");
  if (scheme?.toLowerCase() !== "basic" || !encoded) return null;
  const decoded = Buffer.from(encoded, "base64").toString("utf8");
  const split = decoded.indexOf(":");
  return split < 0 ? null : { user: decoded.slice(0, split), password: decoded.slice(split + 1) };
}

const noStore = { "Cache-Control": "no-store" };

/**
 * Phase 1 has no login, which is fine on a developer machine. In production the dashboard and
 * its BFF stay closed unless HTTP Basic credentials are configured, and fail closed (503) when
 * they are not. Returns a response to send instead of the page, or null to let the request through.
 */
export function guardDashboard(request: Request, env: GuardEnv): Response | null {
  if (env.APP_ENV !== "production") return null;
  if (!isProtectedPath(new URL(request.url).pathname)) return null;

  if (!env.DASHBOARD_USER || !env.DASHBOARD_PASSWORD) {
    return new Response(
      "The dashboard is disabled: set DASHBOARD_USER and DASHBOARD_PASSWORD to enable it in production.",
      { status: 503, headers: { ...noStore, "Content-Type": "text/plain; charset=utf-8" } },
    );
  }
  const given = credentialsFrom(request.headers.get("authorization"));
  // Evaluate both comparisons so timing does not reveal which part was wrong.
  const userOk = equal(given?.user ?? "", env.DASHBOARD_USER);
  const passwordOk = equal(given?.password ?? "", env.DASHBOARD_PASSWORD);
  if (given && userOk && passwordOk) return null;
  return new Response("Authentication required.", {
    status: 401,
    headers: { ...noStore, "WWW-Authenticate": 'Basic realm="Lead Qualifier", charset="UTF-8"' },
  });
}
