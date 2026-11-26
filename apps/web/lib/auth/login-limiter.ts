/**
 * Sliding window of sign-in attempts per key (in memory: one web process, one admin).
 * ``acquire`` checks and records in one synchronous step, so parallel requests cannot all pass the
 * check before any of them is counted; a successful sign-in gives its attempt back with ``release``.
 */
export class LoginLimiter {
  private attempts = new Map<string, number[]>();

  constructor(
    private readonly max: number,
    private readonly windowMs: number,
    private readonly now: () => number = Date.now,
  ) {}

  private recent(key: string): number[] {
    const cutoff = this.now() - this.windowMs;
    const kept = (this.attempts.get(key) ?? []).filter((t) => t > cutoff);
    if (kept.length) this.attempts.set(key, kept);
    else this.attempts.delete(key);
    return kept;
  }

  /** Counts an attempt unless the key is locked. ``retryAfterSeconds`` is 0 when it was allowed. */
  acquire(key: string): { ok: boolean; retryAfterSeconds: number; count: number } {
    const kept = this.recent(key);
    if (kept.length >= this.max) {
      return {
        ok: false,
        retryAfterSeconds: Math.max(1, Math.ceil((kept[0] + this.windowMs - this.now()) / 1000)),
        count: kept.length,
      };
    }
    this.attempts.set(key, [...kept, this.now()]);
    return { ok: true, retryAfterSeconds: 0, count: kept.length + 1 };
  }

  /** Forget every attempt of ``key`` (it signed in). */
  reset(key: string): void {
    this.attempts.delete(key);
  }

  /** Undo the newest attempt of ``key`` (it was a successful sign-in). */
  release(key: string): void {
    const kept = this.recent(key);
    kept.pop();
    if (kept.length) this.attempts.set(key, kept);
    else this.attempts.delete(key);
  }
}

/** Delay before answering the n-th attempt in the window: none for the first few, then doubling. */
export function slowdownMs(count: number, free = 5, base = 250, cap = 8000): number {
  return count <= free ? 0 : Math.min(cap, base * 2 ** (count - free - 1));
}
