import { NextResponse, type NextRequest } from "next/server";
import { guardDashboard } from "@/lib/auth/dashboard-guard";

/** Per-request CSP nonce plus baseline security headers for every page. */
export function proxy(request: NextRequest) {
  const denied = guardDashboard(request, {
    APP_ENV: process.env.APP_ENV,
    DASHBOARD_USER: process.env.DASHBOARD_USER,
    DASHBOARD_PASSWORD: process.env.DASHBOARD_PASSWORD,
  });

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  let apiOrigin = "";
  try {
    apiOrigin = new URL(process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000").origin;
  } catch {
    apiOrigin = "";
  }
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isDev ? " 'unsafe-eval'" : ""}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self' ${apiOrigin}`.trim(),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  let response: Response;
  if (denied) {
    // 401/503 from the dashboard guard get the same hardening as any page.
    response = denied;
  } else {
    const headers = new Headers(request.headers);
    headers.set("x-nonce", nonce);
    headers.set("Content-Security-Policy", csp);
    response = NextResponse.next({ request: { headers } });
  }
  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return response;
}

export const config = {
  matcher: [
    // Deliberately no prefetch exclusion: prefetch requests must pass the dashboard guard too.
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
