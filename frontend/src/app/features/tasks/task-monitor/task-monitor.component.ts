/**
 * TaskMonitorComponent — real-time agent task monitor.
 *
 * Features:
 *   - Lists all AgentTasks from GET /api/v1/tasks.
 *   - Live status updates via SignalR `task_updated` events.
 *   - Status filter chips (All / Pending / In Progress / Completed / Failed).
 *   - Detail side panel showing structured agent output and metadata.
 *
 * US-022 / US-048: SignalR integration for real-time dashboard updates.
 */
import {
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatBadgeModule } from '@angular/material/badge';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Subscription } from 'rxjs';

import { EncounterTasksApiService } from '@core/api';
import { SignalRService } from '@core/signalr';
import { AgentTaskResponse, AGENT_TYPE_DISPLAY_NAME, TaskStatus } from '@core/models';

type StatusFilter = 'ALL' | TaskStatus;

@Component({
  selector: 'app-task-monitor',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatIconModule,
    MatButtonModule,
    MatCardModule,
    MatChipsModule,
    MatTableModule,
    MatBadgeModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './task-monitor.component.html',
  styleUrls: ['./task-monitor.component.scss'],
})
export class TaskMonitorComponent implements OnInit, OnDestroy {
  private readonly tasksApi = inject(EncounterTasksApiService);
  private readonly signalR = inject(SignalRService);

  private taskUpdateSub?: Subscription;

  readonly isLoading = signal<boolean>(true);
  readonly errorMessage = signal<string | null>(null);
  readonly tasks = signal<AgentTaskResponse[]>([]);
  readonly selectedTask = signal<AgentTaskResponse | null>(null);
  readonly statusFilter = signal<StatusFilter>('ALL');
  readonly connectionState = this.signalR.connectionState;

  readonly displayedColumns = [
    'agentType',
    'status',
    'encounterId',
    'unitId',
    'startedAt',
    'completedAt',
    'actions',
  ];

  readonly statusFilters: { label: string; value: StatusFilter }[] = [
    { label: 'All', value: 'ALL' },
    { label: 'Pending', value: TaskStatus.PENDING },
    { label: 'In Progress', value: TaskStatus.IN_PROGRESS },
    { label: 'Completed', value: TaskStatus.COMPLETED },
    { label: 'Failed', value: TaskStatus.FAILED },
  ];

  readonly filteredTasks = computed(() => {
    const filter = this.statusFilter();
    if (filter === 'ALL') {
      return this.tasks();
    }
    return this.tasks().filter((t) => t.status?.toUpperCase() === filter);
  });

  readonly taskCounts = computed(() => {
    const counts: Record<string, number> = { ALL: this.tasks().length };
    for (const t of this.tasks()) {
      const status = t.status?.toUpperCase() ?? 'UNKNOWN';
      counts[status] = (counts[status] ?? 0) + 1;
    }
    return counts;
  });

  ngOnInit(): void {
    this.loadTasks();
    this.taskUpdateSub = this.signalR.taskUpdated$.subscribe((payload) => {
      const taskId = payload.taskId ?? payload.task_id;
      const newStatus = payload.newStatus ?? payload.new_status;
      if (!taskId || !newStatus) {
        return;
      }
      this.patchTaskStatus(taskId, newStatus);
      if (this.selectedTask()?.id === taskId) {
        this.refreshSelectedTask(taskId);
      }
    });
  }

  ngOnDestroy(): void {
    this.taskUpdateSub?.unsubscribe();
  }

  loadTasks(): void {
    this.isLoading.set(true);
    this.errorMessage.set(null);
    this.tasksApi.getMyTasks().subscribe({
      next: (tasks) => {
        this.tasks.set(tasks);
        this.isLoading.set(false);
      },
      error: (err: Error) => {
        this.errorMessage.set(err.message);
        this.isLoading.set(false);
      },
    });
  }

  selectTask(task: AgentTaskResponse): void {
    this.selectedTask.set(task);
  }

  closeDetail(): void {
    this.selectedTask.set(null);
  }

  setFilter(filter: StatusFilter): void {
    this.statusFilter.set(filter);
  }

  agentDisplayName(agentType: string | null): string {
    if (!agentType) {
      return 'Unknown';
    }
    return AGENT_TYPE_DISPLAY_NAME[agentType.toLowerCase()] ?? agentType;
  }

  statusClass(status: string | null): string {
    if (!status) {
      return 'status-unknown';
    }
    switch (status.toUpperCase()) {
      case TaskStatus.COMPLETED:
        return 'status-completed';
      case TaskStatus.IN_PROGRESS:
        return 'status-in-progress';
      case TaskStatus.PENDING:
        return 'status-pending';
      case TaskStatus.FAILED:
        return 'status-failed';
      case TaskStatus.BLOCKED:
        return 'status-blocked';
      default:
        return 'status-unknown';
    }
  }

  private patchTaskStatus(taskId: string, newStatus: string): void {
    this.tasks.update((list) =>
      list.map((t) =>
        t.id === taskId ? { ...t, status: newStatus.toUpperCase() } : t
      )
    );
  }

  private refreshSelectedTask(taskId: string): void {
    this.tasksApi.getTaskById(taskId).subscribe({
      next: (task) => this.selectedTask.set(task),
      error: (err: Error) => console.error('Failed to refresh task detail', err),
    });
  }
}
