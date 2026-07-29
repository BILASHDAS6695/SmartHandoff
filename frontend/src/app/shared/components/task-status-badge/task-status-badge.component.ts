/**
 * TaskStatusBadgeComponent — reusable badge displaying the current status of an agent task.
 * Reactively updates when a `task_updated` SignalR event is received for the given taskId.
 *
 * US-048 TASK-004
 */
import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TaskUpdateHandlerService } from '@core/signalr/handlers/task-update-handler.service';

type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';

/**
 * Reusable badge displaying the current status of an agent task.
 * Reactively updates when a `task_updated` SignalR event is received for the given taskId.
 *
 * Usage:
 *   <app-task-status-badge
 *     [taskId]="'task-uuid-123'"
 *     [taskName]="'Documentation Agent'"
 *     [initialStatus]="'IN_PROGRESS'"
 *   />
 */
@Component({
  selector: 'app-task-status-badge',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, MatIconModule, MatTooltipModule],
  templateUrl: './task-status-badge.component.html',
  styleUrl: './task-status-badge.component.scss',
})
export class TaskStatusBadgeComponent implements OnInit {
  /** The unique task identifier — used to look up live status from the handler. */
  @Input({ required: true }) taskId!: string;

  /** Human-readable task name shown in the tooltip. */
  @Input({ required: true }) taskName!: string;

  /**
   * Initial status to display before any real-time update arrives.
   * Sourced from the REST response when the page first loads.
   */
  @Input() initialStatus: TaskStatus = 'PENDING';

  private readonly taskHandler = inject(TaskUpdateHandlerService);

  /** Overriding status from SignalR — null until first update received for this task. */
  private readonly _liveStatus = signal<TaskStatus | null>(null);

  /**
   * Resolved status: live status takes precedence over initial status.
   * This computed signal re-evaluates whenever either signal changes.
   */
  protected readonly status = computed<TaskStatus>(
    () => this._liveStatus() ?? this.initialStatus,
  );

  protected readonly statusLabel = computed(() => {
    const labels: Record<TaskStatus, string> = {
      PENDING: 'Pending',
      IN_PROGRESS: 'In Progress',
      COMPLETED: 'Completed',
      FAILED: 'Failed',
    };
    return labels[this.status()];
  });

  protected readonly statusIcon = computed(() => {
    const icons: Record<TaskStatus, string> = {
      PENDING: 'schedule',
      IN_PROGRESS: 'sync',
      COMPLETED: 'check_circle',
      FAILED: 'error',
    };
    return icons[this.status()];
  });

  protected readonly isSpinning = computed(
    () => this.status() === 'IN_PROGRESS',
  );

  ngOnInit(): void {
    // Check if a live update has already arrived before this component mounted
    // (e.g., the task completed before the user navigated to the patient detail page)
    const existing = this.taskHandler.getTaskStatus(this.taskId);
    if (existing) {
      this._liveStatus.set(existing.newStatus);
    }

    // Subscribe to future updates via the task handler's taskStatusMap signal
    // The handler maintains the authoritative map; this component reads from it
  }

  /**
   * Called by TaskUpdateHandlerService consumer pattern — updates internal live status.
   * This method is invoked from a parent container that subscribes to task updates
   * for all tasks visible in the current view, avoiding N individual subscriptions.
   *
   * @param newStatus - The incoming task status from the SignalR event
   */
  updateStatus(newStatus: TaskStatus): void {
    this._liveStatus.set(newStatus);
  }
}
