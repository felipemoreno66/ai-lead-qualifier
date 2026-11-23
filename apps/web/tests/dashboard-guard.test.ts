import { describe, expect, it } from "vitest";
import {
  authState,
  guardDashboard,
  guardRequest,
  isPublicPath,
  normalizePath,
} from "@/lib/auth/dashboard-guard";

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

  it("leaves only the public form, thank-you, privacy notice and static assets open", () => {
    const open = [
      "/",
      "/w/northwind-academy/apply",
      "/w/northwind-academy/apply/thanks",
      "/privacy/northwind-academy",
      "/_next/static/chunks/app.js",
      "/_next/image",
      "/favicon.ico",
      "/robots.txt",
    ];
    for (const path of open) {
      expect(isPublicPath(path), path).toBe(true);
      expect(guardDashboard(req(path), prod), path).toBeNull();
    }
  });

  it("blocks every variant of the protected routes (encoding, slashes, case, trailing, dots)", () => {
    const variants = [
      "/dashboard", "/dashboard/", "/Dashboard", "/DASHBOARD/leads/1", "//dashboard", "///dashboard//leads",
      "/%64ashboard", "/%64%61shboard/leads", "/%2564ashboard", "/dashboard/%2e%2e/dashboard", "/w/../dashboard",
      "/./dashboard", "/bff/leads", "/BFF/leads", "//bff//leads", "/%62ff/leads", "/bff/", "/bff",
      "/dashboard;x=1", "/dashboard%00", "/dashboard%2fleads", "/dashboard\\leads", "/unknown", "/api/x",
      "/w/northwind-academy/other", "/privacy", "/privacy/a/b", "/_next/data/x.json", "/%zz",
    ];
    for (const path of variants) {
      expect(guardDashboard(req(path), prod)?.status, path).toBe(401);
      expect(guardDashboard(req(path), { APP_ENV: "production" })?.status, path).toBe(503);
    }
  });

  it("normalises paths before matching", () => {
    expect(normalizePath("//a/./b/../C/")).toBe("/a/c");
    expect(normalizePath("/%2564ashboard")).toBe("/dashboard");
    expect(normalizePath("/%zz")).toBeNull();
  });

  it("route-level and layout-level checks use the same credentials", () => {
    expect(guardRequest(req("/anything"), prod)?.status).toBe(401);
    expect(guardRequest(req("/anything", basic("ops", prod.DASHBOARD_PASSWORD)), prod)).toBeNull();
    expect(guardRequest(req("/anything"), { APP_ENV: "local" })).toBeNull();
    expect(authState(null, { APP_ENV: "production" })).toBe("unconfigured");
    expect(authState(basic("ops", prod.DASHBOARD_PASSWORD), prod)).toBe("ok");
    expect(authState(basic("ops", "x"), prod)).toBe("denied");
    expect(authState(null, {})).toBe("open");
  });
});
