import { hash as argonHash, verify as argonVerify } from "@node-rs/argon2";
import { APIError, betterAuth } from "better-auth";
import { memoryAdapter, type MemoryDB } from "better-auth/adapters/memory";
import { createAuthMiddleware } from "better-auth/api";
import { authMode, type AuthEnv } from "./mode";
import { LoginLimiter, slowdownMs, WindowCounter } from "./login-limiter";
import { QueueFull, SerialQueue } from "./serial-queue";

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

type Limits = { perClient: number; maxQueued: number; sleep: (ms: number) => Promise<void> };
const defaultLimits: Limits = {
  perClient: 5,
  maxQueued: 50,
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
  // Instance-wide: never refuses, only slows every attempt down while many are failing (constant
  // memory). Sign-ins are also verified one at a time, so the slowdown caps throughput.
  const everyone = new WindowCounter(windowMs);
  const signIns = new SerialQueue(limits.maxQueued);
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
        // Built-in limiter as an upper bound on sign-in requests. Without a trusted client identity
        // every client shares one bucket, so its threshold is high: it bounds a flood without
        // locking the operator out for more than a window.
        [SIGN_IN_PATH]: (request) =>
          clientKey(request.headers) ? { window: 60, max: 30 } : { window: 60, max: 120 },
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
        const delay = slowdownMs(everyone.hit());
        if (delay > 0) await limits.sleep(delay);
      }),
      after: createAuthMiddleware(async (ctx) => {
        if (ctx.path !== SIGN_IN_PATH || !ctx.context.newSession) return;
        // A correct password gives its attempt back: only failures count towards the limits.
        const key = keyOf(ctx);
        if (key) perClient.reset(key);
        everyone.release();
      }),
    },
  });

  // One sign-in verification at a time: parallel guesses queue behind the slowdown.
  const handle = auth.handler;
  auth.handler = async (request) => {
    if (!new URL(request.url).pathname.endsWith(SIGN_IN_PATH)) return handle(request);
    try {
      return await signIns.run(() => handle(request));
    } catch (error) {
      if (!(error instanceof QueueFull)) throw error;
      return Response.json(
        { message: "Too many sign-in attempts. Try again later.", code: "TOO_MANY_REQUESTS" },
        { status: 429, headers: { "Retry-After": "30" } },
      );
    }
  };

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
