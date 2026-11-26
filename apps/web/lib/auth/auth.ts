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

/** Largest sign-in body read; a real one is a few hundred bytes. */
export const MAX_SIGN_IN_BODY_BYTES = 4096;

type Limits = {
  perClient: number;
  /** Password checks waiting for their turn (one runs at a time). */
  maxQueued: number;
  /** Longest a sign-in request may take end to end, queue and delays included. */
  timeoutMs: number;
  sleep: (ms: number) => Promise<void>;
};
const defaultLimits: Limits = {
  perClient: 5,
  maxQueued: 20,
  timeoutMs: 10_000,
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
};

export async function createAuth(
  env: AuthEnv,
  store: MemoryDB = emptyStore(),
  overrides: Partial<Limits> = {},
) {
  const limits: Limits = { ...defaultLimits, ...overrides };
  if (authMode(env) !== "session") throw new Error("Login is not configured");
  const production = env.APP_ENV === "production";
  const adminEmail = (env.ADMIN_EMAIL ?? "").trim().toLowerCase();
  const passwordHash = (env.ADMIN_PASSWORD_HASH ?? "").trim();
  const windowMs = 15 * 60 * 1000;
  // Hard lock per identified client only: other people's failures never lock the operator out.
  const perClient = new LoginLimiter(limits.perClient, windowMs);
  // Instance-wide counter (two numbers of state): only slows attempts down, never refuses them.
  const everyone = new WindowCounter(windowMs);
  // Password checks run one at a time: their cost bounds guesses per second for the whole
  // instance. Only the check holds the turn; delays and body reading happen outside it.
  const checks = new SerialQueue(limits.maxQueued);
  const busy = () =>
    new APIError(
      "TOO_MANY_REQUESTS",
      { message: "Too many sign-in attempts. Try again later." },
      new Headers({ "Retry-After": "5" }),
    );
  const queued = async <T>(task: () => Promise<T>): Promise<T> => {
    try {
      return await checks.run(task);
    } catch (error) {
      throw error instanceof QueueFull ? busy() : error;
    }
  };
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
        hash: (password) => queued(() => argonHash(password)),
        verify: ({ hash, password }) =>
          queued(async () => {
            try {
              return await argonVerify(hash, password);
            } catch {
              return false;
            }
          }),
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
        // Built-in limiter for identified clients. Without a trusted identity every client would
        // share one bucket and could refuse the operator, so there the verification queue, the
        // body cap and a short delay bound a flood instead.
        [SIGN_IN_PATH]: (request) =>
          clientKey(request.headers) ? { window: 60, max: 30 } : false,
      },
    },
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        if (ctx.path !== SIGN_IN_PATH) return;
        const key = keyOf(ctx);
        const overall = everyone.hit();
        let delay: number;
        if (key) {
          const lock = perClient.acquire(key);
          if (!lock.ok) {
            throw new APIError(
              "TOO_MANY_REQUESTS",
              { message: "Too many sign-in attempts. Try again later." },
              new Headers({ "Retry-After": String(lock.retryAfterSeconds) }),
            );
          }
          delay = slowdownMs(lock.count, 3); // progressive, for this client only
        } else {
          delay = slowdownMs(overall, 5, 250, 2000); // small and capped: nobody is locked out
        }
        if (delay > 0) await limits.sleep(delay); // outside the verification turn
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

  const handle = auth.handler;
  auth.handler = async (request) => {
    if (!new URL(request.url).pathname.endsWith(SIGN_IN_PATH)) return handle(request);
    const body = await readCapped(request, MAX_SIGN_IN_BODY_BYTES);
    if (body === null) return refuse(413, "The request is too large.");
    const bounded = new Request(request.url, { method: request.method, headers: request.headers, body });
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<Response>((resolve) => {
      timer = setTimeout(() => resolve(refuse(503, "Sign-in is busy. Try again shortly.", 5)), limits.timeoutMs);
    });
    try {
      return await Promise.race([handle(bounded), timeout]);
    } finally {
      clearTimeout(timer);
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

function refuse(status: number, message: string, retryAfter?: number): Response {
  return Response.json(
    { message },
    { status, headers: retryAfter ? { "Retry-After": String(retryAfter) } : {} },
  );
}

/** The request body as text, or null when it is larger than `limit` bytes (read as a stream). */
async function readCapped(request: Request, limit: number): Promise<string | null> {
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > limit) return null;
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }
  return Buffer.concat(chunks).toString("utf8");
}
