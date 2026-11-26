import { authMode, UNCONFIGURED_MESSAGE, type AuthEnv } from "./mode";

export type GuardEnv = AuthEnv;

/** Answers whether the request headers carry a valid operator session. */
export type SessionVerifier = (headers: Headers) => Promise<boolean>;

/**
 * Routes that stay public when the login is on. Everything else is closed (fail closed), so a new route
 * is protected by default and path-normalisation tricks cannot reach a protected page.
 */
const PUBLIC_ROUTES: RegExp[] = [
  /^\/$/,
  /^\/w\/[a-z0-9-]+\/apply$/,
  /^\/w\/[a-z0-9-]+\/apply\/thanks$/,
  /^\/privacy\/[a-z0-9-]+$/,
  /^\/login$/,
  // Only the two Better Auth endpoints the login page uses; sign-up and the rest stay closed.
  /^\/api\/auth\/(sign-in\/email|sign-out)$/,
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

const noStore = { "Cache-Control": "no-store" };

function unconfigured(): Response {
  return new Response(UNCONFIGURED_MESSAGE, {
    status: 503,
    headers: { ...noStore, "Content-Type": "text/plain; charset=utf-8" },
  });
}

function unauthorized(): Response {
  return Response.json(
    { title: "Authentication required", detail: "Sign in to continue." },
    { status: 401, headers: noStore },
  );
}

/** Pages go to the login (with a return path); API-style routes get a plain 401. */
function toLogin(url: URL): Response {
  const next = url.pathname + url.search;
  return new Response(null, {
    status: 303,
    headers: { ...noStore, Location: `/login?next=${encodeURIComponent(next)}` },
  });
}

const isApiPath = (pathname: string) => /^\/(bff|api)(\/|$)/.test(normalizePath(pathname) ?? "");

/**
 * Edge check (proxy): with the login on, every request outside the public allow-list needs a valid
 * session; the dashboard stays closed (503) while the login is missing or incomplete. Without any
 * `ADMIN_*` outside production there is no login (the keyless demo). Returns a response to send
 * instead of the page, or null to let the request through.
 */
export async function guardDashboard(
  request: Request,
  env: GuardEnv,
  verify: SessionVerifier,
): Promise<Response | null> {
  const mode = authMode(env);
  if (mode === "off") return null;
  const url = new URL(request.url);
  if (isPublicPath(url.pathname)) return null;
  if (mode === "unconfigured") return unconfigured();
  if (await verify(request.headers)) return null;
  return isApiPath(url.pathname) ? unauthorized() : toLogin(url);
}

/** Defense in depth for route handlers and layouts that must not rely on the proxy alone. */
export async function guardRequest(
  request: Request,
  env: GuardEnv,
  verify: SessionVerifier,
): Promise<Response | null> {
  const mode = authMode(env);
  if (mode === "off") return null;
  if (mode === "unconfigured") return unconfigured();
  return (await verify(request.headers)) ? null : unauthorized();
}
