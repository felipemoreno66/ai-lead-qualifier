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
        ...(ip ? { "x-forwarded-for": `10.0.0.1, ${ip}` } : {}),
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

  it("counts parallel attempts atomically (no burst gets past the limit)", async () => {
    const auth = await createAuth(await proxied(), undefined, limits());
    const results = await Promise.all(
      Array.from({ length: 8 }, () => signIn(auth, "nope", ADMIN_EMAIL, ATTACKER)),
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
