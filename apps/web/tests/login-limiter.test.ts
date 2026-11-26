import { describe, expect, it } from "vitest";
import { LoginLimiter } from "@/lib/auth/login-limiter";

describe("LoginLimiter", () => {
  it("locks a key after max failures and reports the wait", () => {
    let now = 0;
    const limiter = new LoginLimiter(3, 60_000, () => now);
    for (let i = 0; i < 3; i++) {
      expect(limiter.retryAfterSeconds("a")).toBe(0);
      limiter.recordFailure("a");
      now += 1000;
    }
    expect(limiter.retryAfterSeconds("a")).toBe(57);
    expect(limiter.retryAfterSeconds("b")).toBe(0);
  });

  it("forgets failures after the window and on reset", () => {
    let now = 0;
    const limiter = new LoginLimiter(2, 60_000, () => now);
    limiter.recordFailure("a");
    limiter.recordFailure("a");
    now = 60_001;
    expect(limiter.retryAfterSeconds("a")).toBe(0);
    limiter.recordFailure("a");
    limiter.recordFailure("a");
    limiter.reset("a");
    expect(limiter.retryAfterSeconds("a")).toBe(0);
  });
});
