import { hash as argonHash, verify as argonVerify } from "@node-rs/argon2";
import { APIError, betterAuth } from "better-auth";
import { memoryAdapter, type MemoryDB } from "better-auth/adapters/memory";
import { createAuthMiddleware } from "better-auth/api";
import { authMode, type AuthEnv } from "./mode";
import { LoginLimiter, slowdownMs } from "./login-limiter";

const SIGN_IN_PATH = "/sign-in/email";
const DEFAULT_SESSION_HOURS = 12;

function sessionSeconds(env: AuthEnv): number {
  const hours = Number(env.ADMIN_SESSION_HOURS);
  return Math.round((Number.isFinite(hours) && hours > 0 ? hours : DEFAULT_SESSION_HOURS) * 3600);
}

/**
 * Better Auth for a single operator. The one account lives in memory and is created from
 * `ADMIN_EMAIL` and `ADMIN_PASSWORD_HASH` on first use: nothing is stored, a restart signs the
 * operator out, and rotating the password is an env change plus a restart.
 */
const emptyStore = (): MemoryDB => ({ user: [], session: [], account: [], verification: [], rateLimit: [] });

type Limits = { perClient: number; sleep: (ms: number) => Promise<void> };
const defaultLimits: Limits = {
  perClient: 5,
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

export async function createAuth(env: AuthEnv, store: MemoryDB = emptyStore(), limits = defaultLimits) {
  if (authMode(env) !== "session") throw new Error("Login is not configured");
  const production = env.APP_ENV === "production";
  const adminEmail = (env.ADMIN_EMAIL ?? "").trim().toLowerCase();
  const passwordHash = (env.ADMIN_PASSWORD_HASH ?? "").trim();
  const windowMs = 15 * 60 * 1000;
  // Hard lock per identified client only: other people's failures never lock the operator out.
  const perClient = new LoginLimiter(limits.perClient, windowMs);
  // Instance-wide: never refuses, only slows every attempt down while many are failing.
  const everyone = new LoginLimiter(Number.MAX_SAFE_INTEGER, windowMs);
  const trustForwarded = env.TRUST_FORWARDED_HOST === "true";
  /** Client identity: the last X-Forwarded-For hop, which only a proxy we trust appends. */
  const clientKey = (headers?: Headers): string | null =>
    (trustForwarded && headers?.get("x-forwarded-for")?.split(",").pop()?.trim()) || null;
  const keyOf = (ctx: { headers?: Headers }) => clientKey(ctx.headers);

  const auth = betterAuth({
    appName: "Lead Qualifier",
    baseURL: env.BETTER_AUTH_URL || undefined,
    secret: env.BETTER_AUTH_SECRET,
    database: memoryAdapter(store),
    emailAndPassword: {
      enabled: true,
      disableSignUp: true,
      password: {
        hash: (password) => argonHash(password),
        verify: async ({ hash, password }) => {
          try {
            return await argonVerify(hash, password);
          } catch {
            return false;
          }
        },
      },
    },
    session: { expiresIn: sessionSeconds(env), updateAge: 60 * 60 },
    advanced: {
      useSecureCookies: production,
      defaultCookieAttributes: { httpOnly: true, sameSite: "lax", secure: production },
    },
    // Sign-in has its own failed-attempt lockout below; the built-in limiter covers the other paths.
    rateLimit: {
      enabled: true,
      window: 60,
      max: 60,
      customRules: {
        // Built-in limiter as an upper bound on sign-in requests of an identified client. Without
        // an identity every client would share one bucket and could lock the operator out, so
        // only the slowdown below applies.
        [SIGN_IN_PATH]: (request) =>
          clientKey(request.headers) ? { window: 60, max: 30 } : false,
      },
    },
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        if (ctx.path !== SIGN_IN_PATH) return;
        const key = keyOf(ctx);
        if (key) {
          const lock = perClient.acquire(key);
          if (!lock.ok) {
            throw new APIError("TOO_MANY_REQUESTS", {
              message: "Too many sign-in attempts. Try again later.",
              retryAfter: lock.retryAfterSeconds,
            });
          }
        }
        const { count } = everyone.acquire("*");
        const delay = slowdownMs(count);
        if (delay > 0) await limits.sleep(delay);
      }),
      after: createAuthMiddleware(async (ctx) => {
        if (ctx.path !== SIGN_IN_PATH || !ctx.context.newSession) return;
        // A correct password gives its attempt back: only failures count towards the limits.
        const key = keyOf(ctx);
        if (key) perClient.reset(key);
        everyone.release("*");
      }),
    },
  });

  const context = await auth.$context;
  if (!(await context.internalAdapter.findUserByEmail(adminEmail))) {
    const user = await context.internalAdapter.createUser(
      { email: adminEmail, name: "Admin", emailVerified: true },
      { method: "admin" },
    );
    await context.internalAdapter.linkAccount({
      providerId: "credential",
      accountId: user.id,
      userId: user.id,
      password: passwordHash,
    });
  }
  return auth;
}

export type AdminAuth = Awaited<ReturnType<typeof createAuth>>;
