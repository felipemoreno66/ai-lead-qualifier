/** Sliding-window limiter for failed sign-ins (in memory: one web process, one admin). */
export class LoginLimiter {
  private failures = new Map<string, number[]>();

  constructor(
    private readonly max: number,
    private readonly windowMs: number,
    private readonly now: () => number = Date.now,
  ) {}

  private recent(key: string): number[] {
    const cutoff = this.now() - this.windowMs;
    const kept = (this.failures.get(key) ?? []).filter((t) => t > cutoff);
    if (kept.length) this.failures.set(key, kept);
    else this.failures.delete(key);
    return kept;
  }

  /** Seconds until another attempt is allowed, or 0 when the key is not locked. */
  retryAfterSeconds(key: string): number {
    const kept = this.recent(key);
    if (kept.length < this.max) return 0;
    return Math.max(1, Math.ceil((kept[0] + this.windowMs - this.now()) / 1000));
  }

  recordFailure(key: string): void {
    this.failures.set(key, [...this.recent(key), this.now()]);
  }

  reset(key: string): void {
    this.failures.delete(key);
  }
}
