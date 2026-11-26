import { NextResponse, type NextRequest } from "next/server";
import { guardDashboard } from "@/lib/auth/dashboard-guard";
import { authEnv, hasSession } from "@/lib/auth/session";
import { isPublicDemo } from "@/lib/public-demo-flag";

/** Per-request CSP nonce plus baseline security headers for every page. */
export async function proxy(request: NextRequest) {
  const denied = await guardDashboard(request, authEnv(), hasSession);

  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isDev = process.env.NODE_ENV === "development";
  const publicDemo = isPublicDemo();
  // Public demo: browsers only ever talk to this server, never to the agent.
  let apiOrigin = "";
  try {
    if (!publicDemo) apiOrigin = new URL(process.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000").origin;
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
    // Redirects, 401 and 503 from the dashboard guard get the same hardening as any page.
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
  if (publicDemo) {
    // Served over HTTPS by Tailscale Funnel: pin it, isolate the origin, expose nothing cross-origin.
    response.headers.set("Strict-Transport-Security", "max-age=31536000");
    response.headers.set("Cross-Origin-Opener-Policy", "same-origin");
    response.headers.set("Cross-Origin-Resource-Policy", "same-origin");
    response.headers.set(
      "Permissions-Policy",
      "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    );
  }
  return response;
}

export const config = {
  matcher: [
    // Deliberately no prefetch exclusion: prefetch requests must pass the dashboard guard too.
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
