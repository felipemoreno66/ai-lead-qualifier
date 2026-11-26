// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAuth } from "@/lib/auth/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD, adminEnv } from "./auth-helpers";

afterEach(() => vi.useRealTimers());

const ATTACKER = "203.0.113.7";
const proxied = () => adminEnv({ TRUST_FORWARDED_HOST: "true" });
const limits = () => ({ perClient: 3, sleep: async () => {} });
const signIn = (
  auth: Awaited<ReturnType<typeof createAuth>>,
  password: string,
  email = ADMIN_EMAIL,
  ip?: string,
) =>
  auth.handler(
    new Request("http://web/api/auth/sign-in/email", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://web",
        ...(ip ? { "x-forwarded-for": ip } : {}),
      },
      body: JSON.stringify({ email, password }),
    }),
  );
const cookieOf = (res: Response) =>
  res.headers
    .getSetCookie()
    .map((c) => c.split(";")[0])
    .join("; ");

describe("operator login", () => {
  it("signs in with the right credentials and sets a hardened session cookie", async () => {
    const auth = await createAuth(await adminEnv());
    const res = await signIn(auth, ADMIN_PASSWORD);
    expect(res.status).toBe(200);
    const [cookie] = res.headers.getSetCookie();
    expect(cookie).toMatch(/HttpOnly/i);
    expect(cookie).toMatch(/SameSite=Lax/i);
    expect(cookie).toMatch(/Secure/i);
    expect(cookie).toMatch(/^__Secure-/);
    const session = await auth.api.getSession({ headers: new Headers({ cookie: cookieOf(res) }) });
    expect(session?.user.email).toBe(ADMIN_EMAIL);
  });

  it("does not mark the cookie Secure outside production (plain http locally)", async () => {
    const auth = await createAuth(await adminEnv({ APP_ENV: "local" }));
    const res = await signIn(auth, ADMIN_PASSWORD);
    expect(res.headers.getSetCookie()[0]).not.toMatch(/Secure/i);
  });

  it("answers wrong password and unknown email the same way", async () => {
    const auth = await createAuth(await adminEnv());
    const wrongPassword = await signIn(auth, "nope");
    const wrongEmail = await signIn(auth, ADMIN_PASSWORD, "someone@example.com");
    expect(wrongPassword.status).toBe(401);
    expect(wrongEmail.status).toBe(401);
    expect(await wrongPassword.json()).toEqual(await wrongEmail.json());
    expect(wrongPassword.headers.getSetCookie()).toEqual([]);
  });

  it("locks sign-in after repeated failures, even for the right password", async () => {
    const auth = await createAuth(await proxied(), undefined, limits());
    for (let i = 0; i < 3; i++) expect((await signIn(auth, "nope", ADMIN_EMAIL, ATTACKER)).status).toBe(401);
    const locked = await signIn(auth, ADMIN_PASSWORD, ADMIN_EMAIL, ATTACKER);
    expect(locked.status).toBe(429);
    expect(locked.headers.getSetCookie()).toEqual([]);
    // Another client (the operator) is not affected by the attacker's failures.
    expect((await signIn(auth, ADMIN_PASSWORD, ADMIN_EMAIL, "198.51.100.9")).status).toBe(200);
  });

  it("a flood of wrong passwords from unidentified clients does not lock out the operator", async () => {
    const delays: number[] = [];
    const sleep = async (ms: number) => void delays.push(ms);
    const auth = await createAuth(await adminEnv(), undefined, { sleep });
    const started = Date.now();
    const flood = await Promise.all(Array.from({ length: 80 }, () => signIn(auth, "nope")));
    const statuses = new Set(flood.map((r) => r.status));
    expect([...statuses].every((s) => s === 401 || s === 429)).toBe(true);
    expect(Math.max(...delays)).toBeLessThanOrEqual(5000); // capped at half the request timeout
    expect(Math.max(...delays)).toBeGreaterThan(2000); // and growing under a flood
    expect((await signIn(auth, ADMIN_PASSWORD)).status).toBe(200);
    expect(Date.now() - started).toBeLessThan(5000);
  });

  it("holds the verification turn while delaying a flood, yet never past the timeout", async () => {
    let active = 0;
    let maxActive = 0;
    let calls = 0;
    const sleep = async () => {
      calls++;
      if (calls <= 15) return; // attempts 6 to 20 are delayed outside the turn
      active++;
      maxActive = Math.max(maxActive, active);
      await new Promise((r) => setTimeout(r, 2));
      active--;
    };
    const auth = await createAuth(await adminEnv(), undefined, { sleep, maxQueued: 100 });
    await Promise.all(Array.from({ length: 40 }, () => signIn(auth, "nope")));
    expect(calls).toBeGreaterThan(30);
    expect(maxActive).toBe(1); // heavy delays queue up one at a time
  });

  it("logs one structured warning, without personal data, when failures pile up", async () => {
    const warn = vi.fn();
    const auth = await createAuth(await proxied(), undefined, {
      perClient: 1000,
      maxQueued: 200,
      sleep: async () => {},
      warn,
    });
    await Promise.all(Array.from({ length: 70 }, (_, i) => signIn(auth, "nope", ADMIN_EMAIL, `192.0.2.${i + 100}`)));
    expect(warn).toHaveBeenCalledTimes(1);
    const [event] = warn.mock.calls[0] as [Record<string, unknown>];
    expect(event).toMatchObject({ event: "login_failures_high", window_seconds: 600 });
    expect(event.failures).toBeGreaterThan(50);
    expect(JSON.stringify(event)).not.toMatch(/192\.0\.2|owner@example|nope/);
    expect(String(event.client)).toMatch(/^[0-9a-f]{8}$/);
  });

  it("answers 429 quickly with Retry-After when the verification queue is full", async () => {
    const auth = await createAuth(await adminEnv(), undefined, { maxQueued: 2, sleep: async () => {} });
    const flood = await Promise.all(Array.from({ length: 12 }, () => signIn(auth, "nope")));
    const refused = flood.filter((r) => r.status === 429);
    expect(refused.length).toBeGreaterThanOrEqual(6);
    expect(refused[0].headers.get("retry-after")).toBe("5");
    expect(flood.filter((r) => r.status === 401).length).toBeGreaterThanOrEqual(1);
    expect((await signIn(auth, ADMIN_PASSWORD)).status).toBe(200); // the queue drains
  });

  it("rejects an oversized body with 413 before any password check", async () => {
    const auth = await createAuth(await adminEnv());
    const res = await auth.handler(
      new Request("http://web/api/auth/sign-in/email", {
        method: "POST",
        headers: { "content-type": "application/json", origin: "http://web" },
        body: JSON.stringify({ email: ADMIN_EMAIL, password: "x".repeat(10_000) }),
      }),
    );
    expect(res.status).toBe(413);
    const streamed = new Request("http://web/api/auth/sign-in/email", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://web" },
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode("x".repeat(5000)));
          controller.close();
        },
      }),
      duplex: "half",
    } as RequestInit);
    expect((await auth.handler(streamed)).status).toBe(413);
  });

  it("never hangs: a slow sign-in ends in 503 with Retry-After", async () => {
    const sleep = () => new Promise<void>((r) => setTimeout(r, 400));
    const auth = await createAuth(await adminEnv(), undefined, { timeoutMs: 50, sleep });
    for (let i = 0; i < 5; i++) await signIn(auth, "nope"); // past the free attempts: now delayed
    const slow = await signIn(auth, "nope");
    expect(slow.status).toBe(503);
    expect(slow.headers.get("retry-after")).toBe("5");
  });

  it("delays an identified client progressively without touching others", async () => {
    const delays: number[] = [];
    const auth = await createAuth(await proxied(), undefined, {
      perClient: 10,
      sleep: async (ms) => void delays.push(ms),
    });
    for (let i = 0; i < 6; i++) await signIn(auth, "nope", ADMIN_EMAIL, "192.0.2.77");
    expect(delays).toEqual([250, 500, 1000]); // attempts 4, 5, 6 of this client
    const other = await signIn(auth, ADMIN_PASSWORD, ADMIN_EMAIL, "198.51.100.77");
    expect(other.status).toBe(200);
  });

  it("counts parallel attempts atomically (no burst gets past the limit)", async () => {
    const auth = await createAuth(await proxied(), undefined, limits());
    const results = await Promise.all(
      Array.from({ length: 8 }, () => signIn(auth, "nope", ADMIN_EMAIL, "192.0.2.55")),
    );
    const statuses = results.map((r) => r.status);
    expect(statuses.filter((s) => s === 401)).toHaveLength(3);
    expect(statuses.filter((s) => s === 429)).toHaveLength(5);
  });

  it("without an identifiable client it only slows down, and a right password still works", async () => {
    const sleep = vi.fn(async () => {});
    const auth = await createAuth(await adminEnv(), undefined, { perClient: 3, sleep });
    for (let i = 0; i < 9; i++) expect((await signIn(auth, "nope")).status).toBe(401);
    expect(sleep).toHaveBeenCalled();
    const delays = sleep.mock.calls.map((c) => (c as unknown as [number])[0]);
    expect(delays).toEqual([...delays].sort((a, b) => a - b));
    expect((await signIn(auth, ADMIN_PASSWORD)).status).toBe(200);
  });

  it("a successful sign-in clears the failure count", async () => {
    const auth = await createAuth(await proxied(), undefined, limits());
    for (let i = 0; i < 2; i++) await signIn(auth, "nope", ADMIN_EMAIL, ATTACKER);
    expect((await signIn(auth, ADMIN_PASSWORD, ADMIN_EMAIL, ATTACKER)).status).toBe(200);
    for (let i = 0; i < 2; i++) expect((await signIn(auth, "nope", ADMIN_EMAIL, ATTACKER)).status).toBe(401);
  });

  it("expires the session after ADMIN_SESSION_HOURS", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    const auth = await createAuth(await adminEnv({ ADMIN_SESSION_HOURS: "2" }));
    const headers = new Headers({ cookie: cookieOf(await signIn(auth, ADMIN_PASSWORD)) });
    expect(await auth.api.getSession({ headers })).not.toBeNull();
    vi.setSystemTime(Date.now() + 3 * 3600 * 1000);
    expect(await auth.api.getSession({ headers })).toBeNull();
  });

  it("signs out: the old cookie stops working", async () => {
    const auth = await createAuth(await adminEnv());
    const headers = new Headers({ cookie: cookieOf(await signIn(auth, ADMIN_PASSWORD)), origin: "http://web" });
    const out = await auth.handler(
      new Request("http://web/api/auth/sign-out", { method: "POST", headers: { ...Object.fromEntries(headers), "content-type": "application/json" }, body: "{}" }),
    );
    expect(out.status).toBe(200);
    expect(await auth.api.getSession({ headers })).toBeNull();
  });

  it("has no sign-up: nobody else can create an account", async () => {
    const auth = await createAuth(await adminEnv());
    const res = await auth.handler(
      new Request("http://web/api/auth/sign-up/email", {
        method: "POST",
        headers: { "content-type": "application/json", origin: "http://web" },
        body: JSON.stringify({ email: "intruder@example.com", password: "password-12345", name: "x" }),
      }),
    );
    expect(res.ok).toBe(false);
    expect((await signIn(auth, "password-12345", "intruder@example.com")).status).toBe(401);
  });

  it("refuses to start without a complete login", async () => {
    await expect(createAuth({ APP_ENV: "production" })).rejects.toThrow(/not configured/);
  });
});
