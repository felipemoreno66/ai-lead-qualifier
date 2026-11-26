/** Runs tasks one at a time, in arrival order, with a bounded number waiting. */
export class QueueFull extends Error {}

export class SerialQueue {
  private tail: Promise<unknown> = Promise.resolve();
  private pending = 0;

  constructor(private readonly maxPending: number) {}

  get waiting(): number {
    return this.pending;
  }

  run<T>(task: () => Promise<T>): Promise<T> {
    if (this.pending >= this.maxPending) return Promise.reject(new QueueFull());
    this.pending++;
    const result = this.tail.then(task, task);
    this.tail = result.catch(() => undefined).finally(() => void this.pending--);
    return result;
  }
}
