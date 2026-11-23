import { createHash, timingSafeEqual } from "node:crypto";

export type GuardEnv = {
  APP_ENV?: string;
  DASHBOARD_USER?: string;
  DASHBOARD_PASSWORD?: string;
};

/**
 * Routes that stay public in production. Everything else is closed (fail closed), so a new route
 * is protected by default and path-normalisation tricks cannot reach a protected page.
 */
const PUBLIC_ROUTES: RegExp[] = [
  /^\/$/,
  /^\/w\/[a-z0-9-]+\/apply$/,
  /^\/w\/[a-z0-9-]+\/apply\/thanks$/,
  /^\/privacy\/[a-z0-9-]+$/,
  /^\/_next\/static\/.+/,
  /^\/_next\/image$/,
  /^\/(favicon\.ico|robots\.txt)$/,
];

/** Decode, collapse slashes, resolve dot segments, drop the trailing slash and lowercase. */
export function normalizePath(pathname: string): string | null {
  let decoded = pathname;
  for (let i = 0; i < 3; i++) {
    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
    } catch {
      return null;
    }
  }
  const segments: string[] = [];
  for (const part of decoded.replace(/\\/g, "/").split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") segments.pop();
    else segments.push(part);
  }
  return "/" + segments.join("/").toLowerCase();
}

export function isPublicPath(pathname: string): boolean {
  const normalized = normalizePath(pathname);
  return normalized !== null && PUBLIC_ROUTES.some((route) => route.test(normalized));
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

export type AuthState = "open" | "ok" | "unconfigured" | "denied";

/** Credentials check only (no path logic). Outside production there is no login (Phase 1). */
export function authState(authorization: string | null, env: GuardEnv): AuthState {
  if (env.APP_ENV !== "production") return "open";
  if (!env.DASHBOARD_USER || !env.DASHBOARD_PASSWORD) return "unconfigured";
  const given = credentialsFrom(authorization);
  // Evaluate both comparisons so timing does not reveal which part was wrong.
  const userOk = equal(given?.user ?? "", env.DASHBOARD_USER);
  const passwordOk = equal(given?.password ?? "", env.DASHBOARD_PASSWORD);
  return given && userOk && passwordOk ? "ok" : "denied";
}

const noStore = { "Cache-Control": "no-store" };

export function denial(state: AuthState): Response | null {
  if (state === "unconfigured")
    return new Response(
      "The dashboard is disabled: set DASHBOARD_USER and DASHBOARD_PASSWORD to enable it in production.",
      { status: 503, headers: { ...noStore, "Content-Type": "text/plain; charset=utf-8" } },
    );
  if (state === "denied")
    return new Response("Authentication required.", {
      status: 401,
      headers: { ...noStore, "WWW-Authenticate": 'Basic realm="Lead Qualifier", charset="UTF-8"' },
    });
  return null;
}

/**
 * Edge check (proxy): in production every request outside the public allow-list needs the
 * dashboard credentials, and the dashboard stays closed (503) while none are configured.
 * Returns a response to send instead of the page, or null to let the request through.
 */
export function guardDashboard(request: Request, env: GuardEnv): Response | null {
  if (env.APP_ENV !== "production") return null;
  if (isPublicPath(new URL(request.url).pathname)) return null;
  return denial(authState(request.headers.get("authorization"), env));
}

/** Defense in depth for route handlers and layouts that must not rely on the proxy alone. */
export function guardRequest(request: Request, env: GuardEnv): Response | null {
  return denial(authState(request.headers.get("authorization"), env));
}
