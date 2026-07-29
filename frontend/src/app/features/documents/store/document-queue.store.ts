import { Injectable } from '@angular/core';
import { signal } from '@angular/core';

/**
 * Store for document queue state.
 * Holds the pending review count, which is updated via:
 * 1. Initial load from DocumentQueueComponent
 * 2. SignalR `document_created` events
 * 3. Real-time document approvals/rejections
 *
 * Used by:
 * - DocumentQueueComponent: reads and updates on load/action
 * - Sidebar badge: exposes count signal
 * - SignalR handler: increments on document_created event
 */
@Injectable({ providedIn: 'root' })
export class DocumentQueueStore {
  /**
   * Current count of pending review documents.
   * Exposed to templates via signal for reactivity.
   */
  readonly count = signal(0);

  /**
   * Sets the count (usually after initial API load).
   */
  setCount(value: number): void {
    this.count.set(value);
  }

  /**
   * Increments the count (called on document_created SignalR event).
   */
  increment(): void {
    this.count.update((c) => c + 1);
  }

  /**
   * Decrements the count (called on document approval/rejection).
   */
  decrement(): void {
    this.count.update((c) => Math.max(0, c - 1));
  }

  /**
   * Resets the count to zero.
   */
  reset(): void {
    this.count.set(0);
  }
}
