/** Settings that decide how the dashboard is protected (read at request time, never at build). */
export type AuthEnv = {
  APP_ENV?: string;
  ADMIN_EMAIL?: string;
  ADMIN_PASSWORD_HASH?: string;
  BETTER_AUTH_SECRET?: string;
  BETTER_AUTH_URL?: string;
  ADMIN_SESSION_HOURS?: string;
  TRUST_FORWARDED_HOST?: string;
};

/**
 * - `off`: no login (local demo, no `ADMIN_*` at all).
 * - `session`: single-admin login with a session cookie.
 * - `unconfigured`: the dashboard must be protected but the login is missing or incomplete; it
 *   stays closed (503). Production without `ADMIN_*`, or any half-filled `ADMIN_*`, ends here.
 */
export type AuthMode = "off" | "session" | "unconfigured";

export const MIN_AUTH_SECRET_LENGTH = 32;

const isArgon2 = (hash: string) => /^\$argon2(id|i|d)\$/.test(hash);

export function authMode(env: AuthEnv): AuthMode {
  const email = env.ADMIN_EMAIL?.trim();
  const hash = env.ADMIN_PASSWORD_HASH?.trim();
  const secret = env.BETTER_AUTH_SECRET ?? "";
  if (email && hash && isArgon2(hash) && secret.length >= MIN_AUTH_SECRET_LENGTH) return "session";
  if (env.APP_ENV === "production" || email || hash) return "unconfigured";
  return "off";
}

export const UNCONFIGURED_MESSAGE =
  "The dashboard is disabled: set ADMIN_EMAIL, ADMIN_PASSWORD_HASH (argon2, see the README) and " +
  "BETTER_AUTH_SECRET (32+ characters) to enable it.";

/** Only same-site paths inside the app are valid post-login targets (no open redirect). */
export function safeNext(value: string | null | undefined): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/dashboard";
  }
  return value.startsWith("/dashboard") ? value : "/dashboard";
}
