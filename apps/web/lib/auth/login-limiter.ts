/**
 * Sliding window of sign-in attempts per key (in memory: one web process, one admin).
 * ``acquire`` checks and records in one synchronous step, so parallel requests cannot all pass the
 * check before any of them is counted; a successful sign-in gives its attempt back with ``release``.
 */
export class LoginLimiter {
  private attempts = new Map<string, number[]>();

  /** Distinct keys kept at once; the oldest are dropped beyond it (bounded memory). */
  static readonly MAX_KEYS = 10_000;

  get size(): number {
    return this.attempts.size;
  }

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
    if (this.attempts.size > LoginLimiter.MAX_KEYS) this.prune();
    return { ok: true, retryAfterSeconds: 0, count: kept.length + 1 };
  }

  /** Evict the oldest inserted key (Map keeps insertion order): O(1), so a flood stays cheap. */
  private prune(): void {
    const oldest = this.attempts.keys().next();
    if (!oldest.done) this.attempts.delete(oldest.value);
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

/** Fixed-window counter: two numbers of state however many attempts arrive. */
export class WindowCounter {
  private start = 0;
  private count = 0;

  constructor(
    private readonly windowMs: number,
    private readonly now: () => number = Date.now,
  ) {}

  /** Counts one attempt and returns how many the current window holds. */
  hit(): number {
    const t = this.now();
    if (t - this.start >= this.windowMs) {
      this.start = t;
      this.count = 0;
    }
    return ++this.count;
  }

  /** Give one attempt back (a successful sign-in). */
  release(): void {
    this.count = Math.max(0, this.count - 1);
  }
}
