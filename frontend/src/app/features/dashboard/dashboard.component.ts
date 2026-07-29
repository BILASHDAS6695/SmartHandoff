/**
 * DashboardComponent — Care team dashboard with real-time task updates.
 *
 * US-022 Integration:
 *   - Establishes SignalR connection on component init
 *   - Subscribes to task_updated events via SignalRService
 *   - Fetches initial task list via EncounterTasksApiService
 *   - Updates task list in real-time when events are received
 *
 * US-048 Integration:
 *   - Uses new connect() method with JoinGroupsRequest
 *   - Subscribes to new event types: adt_event_received, alert_created, bed_status_changed
 *
 * Design:
 *   - Standalone component (Angular 17+)
 *   - Uses signals for reactive state management
 *   - Uses inject() API for dependency injection
 *   - Proper cleanup on component destroy
 */
import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';

import { SignalRService, TaskUpdatedPayload, JoinGroupsRequest } from '../../core/signalr';
import { EncounterTasksApiService } from '../../core/api';
import { AgentTaskResponse, TaskStatus } from '../../core/models';
import { AuthService } from '../../core/auth/auth.service';
import { DocumentQueueComponent } from '../documents/components/document-queue/document-queue.component';
import { DocumentQueueStore } from '../documents/store/document-queue.store';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, DocumentQueueComponent],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly signalR = inject(SignalRService);
  private readonly tasksApi = inject(EncounterTasksApiService);
  private readonly authService = inject(AuthService);
  private readonly queueStore = inject(DocumentQueueStore);

  private taskSub?: Subscription;
  private documentCreatedSub?: Subscription;
  
  // Reactive state using signals
  readonly encounterId = signal<string>('');
  readonly tasks = signal<AgentTaskResponse[]>([]);
  readonly isLoading = signal<boolean>(true);
  readonly isReconnecting = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  // Computed signals for derived state
  readonly pendingTasks = computed(() => 
    this.tasks().filter(t => t.status === TaskStatus.PENDING)
  );
  
  readonly inProgressTasks = computed(() => 
    this.tasks().filter(t => t.status === TaskStatus.IN_PROGRESS)
  );
  
  readonly completedTasks = computed(() => 
    this.tasks().filter(t => t.status === TaskStatus.COMPLETED)
  );

  readonly tasksByRole = computed(() => {
    const grouped = new Map<string, AgentTaskResponse[]>();
    this.tasks().forEach(task => {
      const role = task.target_role ?? 'unassigned';
      if (!grouped.has(role)) {
        grouped.set(role, []);
      }
      grouped.get(role)!.push(task);
    });
    return grouped;
  });

  /** Computed signal: true if current user is a physician */
  readonly isPhysician = computed(() =>
    this.authService.currentUser()?.role === 'physician'
  );

  ngOnInit(): void {
    // Subscribe to document_created events and update queue count for physicians
    this.documentCreatedSub = this.signalR.documentCreated$.subscribe((payload) => {
      // Only update for physicians with PENDING_REVIEW documents
      if (
        payload.status === 'PENDING_REVIEW' &&
        this.authService.currentUser()?.role === 'physician'
      ) {
        this.queueStore.increment();
      }
    });

    // Extract encounter ID from route params
    this.route.params.subscribe(params => {
      const encounterId = params['encounterId'] || params['id'];
      if (encounterId) {
        this.encounterId.set(encounterId);
        this._initialize(encounterId);
      } else {
        this.errorMessage.set('No encounter ID provided');
        this.isLoading.set(false);
      }
    });
  }

  ngOnDestroy(): void {
    this.taskSub?.unsubscribe();
    this.documentCreatedSub?.unsubscribe();
    void this.signalR.disconnect();
  }

  /**
   * Refresh tasks manually — useful when user suspects stale data.
   */
  refreshTasks(): void {
    const encounterId = this.encounterId();
    if (!encounterId) return;

    this.isLoading.set(true);
    this.errorMessage.set(null);

    this.tasksApi.getTasksForEncounter(encounterId).subscribe({
      next: tasks => {
        this.tasks.set(tasks);
        this.isLoading.set(false);
      },
      error: error => {
        this.errorMessage.set(`Failed to refresh tasks: ${error.message}`);
        this.isLoading.set(false);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private async _initialize(encounterId: string): Promise<void> {
    try {
      // 1. Fetch initial task list
      await this._loadInitialTasks(encounterId);

      // 2. Start SignalR connection with group subscriptions
      const currentUser = this.authService.currentUser();
      if (!currentUser) {
        throw new Error('User not authenticated');
      }

      const joinRequest: JoinGroupsRequest = {
        units: currentUser.units || [],
        roles: [currentUser.role] || [],
      };

      await this.signalR.connect(joinRequest);

      // 3. Subscribe to real-time task updates
      this._subscribeToTaskUpdates();

      this.isLoading.set(false);
    } catch (error) {
      this.errorMessage.set(`Failed to initialize dashboard: ${error}`);
      this.isLoading.set(false);
    }
  }

  private async _loadInitialTasks(encounterId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      this.tasksApi.getTasksForEncounter(encounterId).subscribe({
        next: tasks => {
          this.tasks.set(tasks);
          resolve();
        },
        error: error => {
          reject(error);
        }
      });
    });
  }

  private _subscribeToTaskUpdates(): void {
    this.taskSub = this.signalR.taskUpdated$.subscribe({
      next: (event: TaskUpdatedPayload) => {
        this._applyTaskUpdate(event);
      },
      error: (error: unknown) => {
        console.error('SignalR task update error:', error);
        this.errorMessage.set('Real-time updates interrupted. Consider refreshing.');
      }
    });
  }

  private _applyTaskUpdate(event: TaskUpdatedPayload): void {
    const currentTasks = this.tasks();
    const taskIndex = currentTasks.findIndex(t => t.id === event.taskId);

    if (taskIndex >= 0) {
      // Update existing task
      const updatedTasks = [...currentTasks];
      updatedTasks[taskIndex] = {
        ...updatedTasks[taskIndex],
        status: event.newStatus,
        completed_time: event.newStatus === 'COMPLETED' 
          ? event.completedAt || new Date().toISOString()
          : updatedTasks[taskIndex].completed_time,
      };
      this.tasks.set(updatedTasks);
    } else {
      // New task arrived — fetch full details from API
      this.tasksApi.getTaskById(event.taskId).subscribe({
        next: task => {
          this.tasks.set([...this.tasks(), task]);
        },
        error: error => {
          console.error(`Failed to fetch new task ${event.taskId}:`, error);
        }
      });
    }
  }
}
