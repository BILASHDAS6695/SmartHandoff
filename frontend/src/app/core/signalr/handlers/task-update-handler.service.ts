/**
 * TaskUpdateHandlerService — listens to task_updated messages from SignalRService
 * and maintains a map of task statuses keyed by taskId.
 *
 * US-048 TASK-002
 */
import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService } from '../signalr.service';
import { TaskUpdatedPayload } from '../signalr.models';

/**
 * Listens to `taskUpdated$` from SignalRService and maintains a map of
 * task statuses keyed by `taskId`. Task status badge components derive their
 * display state from this map.
 */
@Injectable({ providedIn: 'root' })
export class TaskUpdateHandlerService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly sub: Subscription;

  // Map<taskId, TaskUpdatedPayload> — latest state per task
  private readonly _taskStatusMap = signal<Map<string, TaskUpdatedPayload>>(
    new Map(),
  );

  /** Immutable snapshot of the task status map. */
  readonly taskStatusMap = this._taskStatusMap.asReadonly();

  constructor() {
    this.sub = this.signalR.taskUpdated$.subscribe((update) => {
      this._taskStatusMap.update((map) => {
        // Replace the entry — creates a new Map to trigger signal reactivity
        const next = new Map(map);
        next.set(update.taskId, update);
        return next;
      });
    });
  }

  /**
   * Returns the latest status payload for a given task ID.
   * Returns `null` if no update has been received yet for this task.
   */
  getTaskStatus(taskId: string): TaskUpdatedPayload | null {
    return this._taskStatusMap().get(taskId) ?? null;
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
