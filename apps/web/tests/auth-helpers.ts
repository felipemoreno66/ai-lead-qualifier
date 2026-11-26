import { hash } from "@node-rs/argon2";
import { vi } from "vitest";

export const ADMIN_EMAIL = "owner@example.com";
export const ADMIN_PASSWORD = "correct horse battery staple";
export const AUTH_SECRET = "test-secret-test-secret-test-secret-0123";

/** argon2 hash of the test password, computed once per test file. */
let cached: Promise<string> | null = null;
export const adminHash = () => (cached ??= hash(ADMIN_PASSWORD));

export async function adminEnv(overrides: Record<string, string> = {}) {
  return {
    APP_ENV: "production",
    ADMIN_EMAIL,
    ADMIN_PASSWORD_HASH: await adminHash(),
    BETTER_AUTH_SECRET: AUTH_SECRET,
    ...overrides,
  };
}

/** Stub the process env with the login configured, and drop the cached auth instance. */
export async function stubLogin(overrides: Record<string, string> = {}) {
  resetAuth();
  for (const [k, v] of Object.entries(await adminEnv(overrides))) vi.stubEnv(k, v);
}

export function resetAuth() {
  delete (globalThis as { __leadqAuth?: unknown }).__leadqAuth;
}

/** Sign in through the real handler and return the Cookie header for later requests. */
export async function signInCookie(env: Record<string, string> = {}): Promise<string> {
  const { getAuth } = await import("@/lib/auth/session");
  const auth = await getAuth();
  const res = await auth.handler(
    new Request("http://web/api/auth/sign-in/email", {
      method: "POST",
      headers: { "content-type": "application/json", origin: "http://web" },
      body: JSON.stringify({ email: ADMIN_EMAIL, password: ADMIN_PASSWORD, ...env }),
    }),
  );
  if (!res.ok) throw new Error(`sign-in failed: ${res.status}`);
  return res.headers
    .getSetCookie()
    .map((c) => c.split(";")[0])
    .join("; ");
}
