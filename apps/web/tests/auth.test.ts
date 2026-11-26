// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { createAuth } from "@/lib/auth/auth";
import { ADMIN_EMAIL, ADMIN_PASSWORD, adminEnv } from "./auth-helpers";

afterEach(() => vi.useRealTimers());

const signIn = (auth: Awaited<ReturnType<typeof createAuth>>, password: string, email = ADMIN_EMAIL) =>
  auth.handler(
    new Request("http://web/api/auth/sign-in/email", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://web" },
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
    const auth = await createAuth(await adminEnv(), undefined, { perKey: 3, global: 25 });
    for (let i = 0; i < 3; i++) expect((await signIn(auth, "nope")).status).toBe(401);
    const locked = await signIn(auth, ADMIN_PASSWORD);
    expect(locked.status).toBe(429);
    expect(locked.headers.getSetCookie()).toEqual([]);
  });

  it("a successful sign-in clears the failure count", async () => {
    const auth = await createAuth(await adminEnv(), undefined, { perKey: 3, global: 25 });
    for (let i = 0; i < 2; i++) await signIn(auth, "nope");
    expect((await signIn(auth, ADMIN_PASSWORD)).status).toBe(200);
    for (let i = 0; i < 2; i++) expect((await signIn(auth, "nope")).status).toBe(401);
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
