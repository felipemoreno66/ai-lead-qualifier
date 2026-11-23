import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "../proxy";

afterEach(() => vi.unstubAllEnvs());

describe("proxy security headers", () => {
  it("applies CSP and hardening headers to guard 401 responses", () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("DASHBOARD_USER", "ops");
    vi.stubEnv("DASHBOARD_PASSWORD", "s3cret");
    const res = proxy(new NextRequest("http://web/dashboard"));
    expect(res.status).toBe(401);
    expect(res.headers.get("Content-Security-Policy")).toContain("frame-ancestors 'none'");
    expect(res.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(res.headers.get("X-Frame-Options")).toBe("DENY");
  });

  it("applies them to guard 503 responses (credentials missing)", () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("DASHBOARD_USER", "");
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    const res = proxy(new NextRequest("http://web/dashboard"));
    expect(res.status).toBe(503);
    expect(res.headers.get("Content-Security-Policy")).toContain("default-src 'self'");
  });

  it("still applies them to normal pages", () => {
    vi.stubEnv("APP_ENV", "local");
    const res = proxy(new NextRequest("http://web/dashboard"));
    expect(res.headers.get("Content-Security-Policy")).toContain("'nonce-");
  });
});
