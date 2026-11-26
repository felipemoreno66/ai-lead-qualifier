import { describe, expect, it, vi } from "vitest";
import { guardDashboard, guardRequest, isPublicPath, normalizePath } from "@/lib/auth/dashboard-guard";
import { authMode, safeNext } from "@/lib/auth/mode";

const req = (path: string) => new Request(`http://web${path}`);
const login = {
  APP_ENV: "production",
  ADMIN_EMAIL: "owner@example.com",
  ADMIN_PASSWORD_HASH: "$argon2id$v=19$m=19456,t=2,p=1$c2FsdA$aGFzaA",
  BETTER_AUTH_SECRET: "9f2c41d7a0b85e63c1d4f7a29b0e3c68",
};
const signedIn = vi.fn(async () => true);
const signedOut = vi.fn(async () => false);

describe("auth mode", () => {
  it("has no login locally without any ADMIN_* (the keyless demo)", () => {
    expect(authMode({})).toBe("off");
    expect(authMode({ APP_ENV: "local" })).toBe("off");
    expect(authMode({ APP_ENV: "test" })).toBe("off");
  });

  it("fails closed in production without the login", () => {
    expect(authMode({ APP_ENV: "production" })).toBe("unconfigured");
    expect(authMode({ ...login, ADMIN_EMAIL: "" })).toBe("unconfigured");
    expect(authMode({ ...login, ADMIN_PASSWORD_HASH: "" })).toBe("unconfigured");
    expect(authMode({ ...login, BETTER_AUTH_SECRET: "short" })).toBe("unconfigured");
    for (const weak of ["x".repeat(40), "ab".repeat(20), "change-me-change-me-change-me-12345", "local-dev-secret-0123456789abcdef"]) {
      expect(authMode({ ...login, BETTER_AUTH_SECRET: weak }), weak).toBe("unconfigured");
    }
  });

  it("refuses a plain-text password in place of a hash", () => {
    expect(authMode({ ...login, ADMIN_PASSWORD_HASH: "hunter2" })).toBe("unconfigured");
    expect(authMode({ ...login, ADMIN_PASSWORD_HASH: "$2b$12$abcdefghijklmnopqrstuv" })).toBe("unconfigured");
  });

  it("refuses weak or non-argon2id hashes (production would not start the login)", () => {
    const weak = "$argon2id$v=19$m=1024,t=1,p=1$c2FsdA$aGFzaA";
    expect(authMode({ ...login, ADMIN_PASSWORD_HASH: weak })).toBe("unconfigured");
    expect(authMode({ ...login, ADMIN_PASSWORD_HASH: "$argon2i$v=19$m=65536,t=3,p=1$c2FsdA$aGFzaA" })).toBe("unconfigured");
    expect(authMode({ ...login, ADMIN_PASSWORD_HASH: "$argon2id$v=19$m=65536,t=3,p=1$c2FsdA$aGFzaA" })).toBe("session");
  });

  it("treats a half-filled login as misconfigured outside production too", () => {
    expect(authMode({ APP_ENV: "local", ADMIN_EMAIL: "owner@example.com" })).toBe("unconfigured");
    expect(authMode({ ...login, APP_ENV: "local" })).toBe("session");
  });

  it("only returns to paths inside the dashboard after sign-in", () => {
    expect(safeNext("/dashboard/leads/1?x=1")).toBe("/dashboard/leads/1?x=1");
    for (const bad of [null, "", "https://evil.test", "//evil.test", "/\\evil", "/login", "/bff/leads"]) {
      expect(safeNext(bad), String(bad)).toBe("/dashboard");
    }
  });
});

describe("dashboard guard", () => {
  it("lets everything through without a login (local demo)", async () => {
    expect(await guardDashboard(req("/dashboard"), {}, signedOut)).toBeNull();
    expect(await guardDashboard(req("/bff/leads"), { APP_ENV: "local" }, signedOut)).toBeNull();
  });

  it("answers 503 while production has no login configured", async () => {
    for (const path of ["/dashboard", "/dashboard/leads/1", "/bff/leads"]) {
      const res = await guardDashboard(req(path), { APP_ENV: "production" }, signedIn);
      expect(res?.status, path).toBe(503);
      expect(await res?.text()).toContain("ADMIN_PASSWORD_HASH");
    }
  });

  it("sends pages without a session to the login and keeps the return path", async () => {
    const res = await guardDashboard(req("/dashboard/leads/42?tab=runs"), login, signedOut);
    expect(res?.status).toBe(303);
    expect(res?.headers.get("location")).toBe(
      "http://web/login?next=%2Fdashboard%2Fleads%2F42%3Ftab%3Druns",
    );
    expect(res?.headers.get("cache-control")).toBe("no-store");
  });

  it("redirects to the host the browser used, not the container's bind address", async () => {
    const request = new Request("http://0.0.0.0:3000/dashboard", { headers: { host: "127.0.0.1:3001" } });
    expect((await guardDashboard(request, login, signedOut))?.headers.get("location")).toBe(
      "http://127.0.0.1:3001/login?next=%2Fdashboard",
    );
    const proxied = new Request("http://0.0.0.0:3000/dashboard", {
      headers: { host: "web:3000", "x-forwarded-host": "dash.example.com", "x-forwarded-proto": "https" },
    });
    const trusting = { ...login, TRUST_FORWARDED_HOST: "true" };
    expect((await guardDashboard(proxied, trusting, signedOut))?.headers.get("location")).toBe(
      "https://dash.example.com/login?next=%2Fdashboard",
    );
    // A configured BETTER_AUTH_URL wins over any header; a junk Host is never reflected.
    const pinned = { ...login, BETTER_AUTH_URL: "https://dash.example.com/" };
    expect((await guardDashboard(request, pinned, signedOut))?.headers.get("location")).toBe(
      "https://dash.example.com/login?next=%2Fdashboard",
    );
    const junk = new Request("http://0.0.0.0:3000/dashboard", { headers: { host: "evil.test/x?y" } });
    expect((await guardDashboard(junk, login, signedOut))?.headers.get("location")).toBe(
      "http://0.0.0.0:3000/login?next=%2Fdashboard",
    );
    // Without a trusted proxy the forwarded headers are ignored.
    expect((await guardDashboard(proxied, login, signedOut))?.headers.get("location")).toBe(
      "http://web:3000/login?next=%2Fdashboard",
    );
  });

  it("answers API-style routes with a JSON 401 instead of a redirect", async () => {
    const res = await guardDashboard(req("/bff/leads"), login, signedOut);
    expect(res?.status).toBe(401);
    expect(res?.headers.get("www-authenticate")).toBeNull();
    expect(await res?.json()).toMatchObject({ title: "Authentication required" });
  });

  it("lets a valid session through", async () => {
    expect(await guardDashboard(req("/dashboard"), login, signedIn)).toBeNull();
    expect(await guardDashboard(req("/bff/leads/abc"), login, signedIn)).toBeNull();
  });

  it("leaves only the public form, privacy notice, login and static assets open", async () => {
    const open = [
      "/",
      "/w/northwind-academy/apply",
      "/w/northwind-academy/apply/thanks",
      "/privacy/northwind-academy",
      "/login",
      "/api/auth/sign-in/email",
      "/api/auth/sign-out",
      "/_next/static/chunks/app.js",
      "/_next/image",
      "/favicon.ico",
      "/robots.txt",
    ];
    for (const path of open) {
      expect(isPublicPath(path), path).toBe(true);
      expect(await guardDashboard(req(path), login, signedOut), path).toBeNull();
    }
  });

  it("blocks every variant of the protected routes (encoding, slashes, case, trailing, dots)", async () => {
    const variants = [
      "/dashboard", "/dashboard/", "/Dashboard", "/DASHBOARD/leads/1", "//dashboard", "///dashboard//leads",
      "/%64ashboard", "/%64%61shboard/leads", "/%2564ashboard", "/dashboard/%2e%2e/dashboard", "/w/../dashboard",
      "/./dashboard", "/bff/leads", "/BFF/leads", "//bff//leads", "/%62ff/leads", "/bff/", "/bff",
      "/dashboard;x=1", "/dashboard%00", "/dashboard%2fleads", "/dashboard\\leads", "/unknown", "/api/x",
      "/api/auth/sign-up/email", "/api/auth/get-session", "/api/auth/sign-in/email/x", "/login/x",
      "/w/northwind-academy/other", "/privacy", "/privacy/a/b", "/_next/data/x.json", "/%zz",
    ];
    for (const path of variants) {
      const res = await guardDashboard(req(path), login, signedOut);
      expect([303, 401], path).toContain(res?.status);
      expect((await guardDashboard(req(path), { APP_ENV: "production" }, signedIn))?.status, path).toBe(503);
    }
  });

  it("normalises paths before matching", () => {
    expect(normalizePath("//a/./b/../C/")).toBe("/a/c");
    expect(normalizePath("/%2564ashboard")).toBe("/dashboard");
    expect(normalizePath("/%zz")).toBeNull();
  });

  it("route-level and layout-level checks use the same session", async () => {
    expect((await guardRequest(req("/anything"), login, signedOut))?.status).toBe(401);
    expect(await guardRequest(req("/anything"), login, signedIn)).toBeNull();
    expect(await guardRequest(req("/anything"), { APP_ENV: "local" }, signedOut)).toBeNull();
    expect((await guardRequest(req("/anything"), { APP_ENV: "production" }, signedIn))?.status).toBe(503);
  });
});
