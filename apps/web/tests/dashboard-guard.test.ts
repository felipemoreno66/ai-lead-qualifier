import { describe, expect, it } from "vitest";
import { guardDashboard, isProtectedPath } from "@/lib/auth/dashboard-guard";

const basic = (user: string, password: string) =>
  `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`;
const req = (path: string, authorization?: string) =>
  new Request(`http://web${path}`, { headers: authorization ? { authorization } : {} });
const prod = { APP_ENV: "production", DASHBOARD_USER: "ops", DASHBOARD_PASSWORD: "s3cret:with:colons" };

describe("dashboard guard", () => {
  it("lets everything through outside production (no login locally)", () => {
    expect(guardDashboard(req("/dashboard"), {})).toBeNull();
    expect(guardDashboard(req("/bff/leads"), { APP_ENV: "local" })).toBeNull();
  });

  it("fails closed with 503 in production when credentials are not configured", async () => {
    for (const path of ["/dashboard", "/dashboard/leads/1", "/bff/leads"]) {
      const res = guardDashboard(req(path), { APP_ENV: "production" });
      expect(res?.status).toBe(503);
      expect(await res?.text()).toContain("DASHBOARD_USER");
    }
    expect(guardDashboard(req("/dashboard"), { ...prod, DASHBOARD_PASSWORD: "" })?.status).toBe(503);
  });

  it("asks for credentials and rejects wrong ones", () => {
    const none = guardDashboard(req("/dashboard"), prod);
    expect(none?.status).toBe(401);
    expect(none?.headers.get("www-authenticate")).toMatch(/^Basic/);
    expect(guardDashboard(req("/dashboard", basic("ops", "wrong")), prod)?.status).toBe(401);
    expect(guardDashboard(req("/dashboard", basic("root", prod.DASHBOARD_PASSWORD)), prod)?.status).toBe(401);
    expect(guardDashboard(req("/dashboard", "Bearer abc"), prod)?.status).toBe(401);
    expect(guardDashboard(req("/bff/leads", "Basic !!!"), prod)?.status).toBe(401);
  });

  it("accepts the right credentials, including passwords with colons", () => {
    expect(guardDashboard(req("/dashboard", basic("ops", prod.DASHBOARD_PASSWORD)), prod)).toBeNull();
    expect(guardDashboard(req("/bff/leads/abc", basic("ops", prod.DASHBOARD_PASSWORD)), prod)).toBeNull();
  });

  it("never caches the challenge", () => {
    expect(guardDashboard(req("/dashboard"), prod)?.headers.get("cache-control")).toBe("no-store");
  });

  it("leaves the public form, privacy notice and static assets open", () => {
    for (const path of ["/w/northwind-academy/apply", "/privacy/northwind-academy", "/", "/dashboardx"]) {
      expect(isProtectedPath(path)).toBe(false);
      expect(guardDashboard(req(path), prod)).toBeNull();
    }
  });
});
