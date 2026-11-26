import { describe, expect, it } from "vitest";
import { LoginLimiter, slowdownMs, WindowCounter } from "@/lib/auth/login-limiter";

describe("LoginLimiter", () => {
  it("counts and locks in one step", () => {
    let now = 0;
    const limiter = new LoginLimiter(3, 60_000, () => now);
    for (let i = 0; i < 3; i++) {
      expect(limiter.acquire("a").ok).toBe(true);
      now += 1000;
    }
    const locked = limiter.acquire("a");
    expect(locked).toMatchObject({ ok: false, retryAfterSeconds: 57 });
    expect(limiter.acquire("b").ok).toBe(true);
  });

  it("forgets attempts after the window and gives back a successful one", () => {
    let now = 0;
    const limiter = new LoginLimiter(2, 60_000, () => now);
    limiter.acquire("a");
    limiter.acquire("a");
    now = 60_001;
    expect(limiter.acquire("a").ok).toBe(true);
    limiter.release("a");
    expect(limiter.acquire("a").ok).toBe(true);
    expect(limiter.acquire("a").ok).toBe(true);
    expect(limiter.acquire("a").ok).toBe(false);
  });

  it("slows down progressively after the free attempts, with a cap", () => {
    expect(slowdownMs(5)).toBe(0);
    expect(slowdownMs(6)).toBe(250);
    expect(slowdownMs(7)).toBe(500);
    expect(slowdownMs(100)).toBe(8000);
  });

  it("keeps memory bounded under a flood of distinct keys", () => {
    const limiter = new LoginLimiter(3, 60_000, () => 0);
    for (let i = 0; i < LoginLimiter.MAX_KEYS * 2; i++) limiter.acquire(`ip-${i}`);
    expect(limiter.size).toBeLessThanOrEqual(LoginLimiter.MAX_KEYS);
  });
});

describe("WindowCounter", () => {
  it("counts in constant memory, restarts each window and takes back successes", () => {
    let now = 0;
    const counter = new WindowCounter(1000, () => now);
    for (let i = 1; i <= 100_000; i++) expect(counter.hit()).toBe(i);
    counter.release();
    expect(counter.hit()).toBe(100_000);
    now = 1000;
    expect(counter.hit()).toBe(1);
  });
});
