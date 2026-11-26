import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "../proxy";
import { signInCookie, stubLogin } from "./auth-helpers";

afterEach(() => vi.unstubAllEnvs());

describe("proxy security headers", () => {
  it("applies CSP and hardening headers to the redirect to the login", async () => {
    await stubLogin();
    const res = await proxy(new NextRequest("http://web/dashboard"));
    expect(res.status).toBe(303);
    expect(res.headers.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("X-Frame-Options")).toBe("DENY");
  });

  it("applies them to guard 503 responses (login not configured)", async () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("ADMIN_EMAIL", "");
    vi.stubEnv("ADMIN_PASSWORD_HASH", "");
    const res = await proxy(new NextRequest("http://web/dashboard"));
    expect(res.status).toBe(503);
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'self'");
  });

  it("lets a signed-in operator through with a nonce", async () => {
    await stubLogin();
    const cookie = await signInCookie();
    const res = await proxy(new NextRequest("http://web/dashboard", { headers: { cookie } }));
    expect(res.headers.get("x-middleware-next")).toBe("1");
    expect(res.headers.get("Content-Security-Policy")).toContain("'nonce-");
  });

  it("still applies them to normal pages without a login (local demo)", async () => {
    vi.stubEnv("APP_ENV", "local");
    const res = await proxy(new NextRequest("http://web/dashboard"));
    expect(res.headers.get("Content-Security-Policy")).toContain("'nonce-");
  });
});
