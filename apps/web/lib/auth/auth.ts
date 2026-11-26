import { hash as argonHash, verify as argonVerify } from "@node-rs/argon2";
import { APIError, betterAuth } from "better-auth";
import { memoryAdapter, type MemoryDB } from "better-auth/adapters/memory";
import { createAuthMiddleware } from "better-auth/api";
import { authMode, type AuthEnv } from "./mode";
import { LoginLimiter } from "./login-limiter";

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

export async function createAuth(env: AuthEnv, store: MemoryDB = emptyStore(), limits = { perKey: 5, global: 25 }) {
  if (authMode(env) !== "session") throw new Error("Login is not configured");
  const production = env.APP_ENV === "production";
  const adminEmail = (env.ADMIN_EMAIL ?? "").trim().toLowerCase();
  const passwordHash = (env.ADMIN_PASSWORD_HASH ?? "").trim();
  const windowMs = 15 * 60 * 1000;
  const perKey = new LoginLimiter(limits.perKey, windowMs);
  const global = new LoginLimiter(limits.global, windowMs);
  const trustForwarded = env.TRUST_FORWARDED_HOST === "true";
  const clientKey = (headers?: Headers) =>
    // Behind a proxy we control the last hop is the client the proxy saw; otherwise one shared key.
    (trustForwarded && headers?.get("x-forwarded-for")?.split(",").pop()?.trim()) || "direct";

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
    rateLimit: { enabled: true, window: 60, max: 60, customRules: { [SIGN_IN_PATH]: false } },
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        if (ctx.path !== SIGN_IN_PATH) return;
        const wait = Math.max(
          perKey.retryAfterSeconds(clientKey(ctx.headers)),
          global.retryAfterSeconds("*"),
        );
        if (wait > 0) {
          throw new APIError("TOO_MANY_REQUESTS", {
            message: "Too many sign-in attempts. Try again later.",
            retryAfter: wait,
          });
        }
      }),
      after: createAuthMiddleware(async (ctx) => {
        if (ctx.path !== SIGN_IN_PATH) return;
        const key = clientKey(ctx.headers);
        if (ctx.context.newSession) {
          perKey.reset(key);
        } else {
          perKey.recordFailure(key);
          global.recordFailure("*");
        }
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
