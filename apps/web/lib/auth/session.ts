import { createAuth, type AdminAuth } from "./auth";
import { authMode, type AuthEnv } from "./mode";

const globalForAuth = globalThis as unknown as { __leadqAuth?: Promise<AdminAuth> };

/** The env the auth settings are read from. Read at call time so the image is env-agnostic. */
export function authEnv(): AuthEnv {
  return {
    APP_ENV: process.env.APP_ENV,
    ADMIN_EMAIL: process.env.ADMIN_EMAIL,
    ADMIN_PASSWORD_HASH: process.env.ADMIN_PASSWORD_HASH,
    BETTER_AUTH_SECRET: process.env.BETTER_AUTH_SECRET,
    BETTER_AUTH_URL: process.env.BETTER_AUTH_URL,
    ADMIN_SESSION_HOURS: process.env.ADMIN_SESSION_HOURS,
    TRUST_FORWARDED_HOST: process.env.TRUST_FORWARDED_HOST,
  };
}

/** One instance per process, shared by the proxy, route handlers and server components. */
export function getAuth(): Promise<AdminAuth> {
  globalForAuth.__leadqAuth ??= createAuth(authEnv());
  return globalForAuth.__leadqAuth;
}

/** True when the request carries a valid, unexpired operator session. */
export async function hasSession(headers: Headers): Promise<boolean> {
  if (authMode(authEnv()) !== "session") return false;
  const auth = await getAuth();
  return (await auth.api.getSession({ headers })) !== null;
}
