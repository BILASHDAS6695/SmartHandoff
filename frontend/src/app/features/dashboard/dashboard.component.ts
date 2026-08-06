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
import { ActivatedRoute, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { Subscription } from 'rxjs';

import { SignalRService, TaskUpdatedPayload, JoinGroupsRequest } from '../../core/signalr';
import { EncounterTasksApiService } from '../../core/api';
import { AgentTaskResponse, TaskStatus } from '../../core/models';
import { AuthService } from '../../core/auth/auth.service';

/** ADT event feed item. */
export interface AdtEvent {
  id: string;
  unit: string;
  patient: string;
  event_type: string;
  location: string;
  time: string;
}

/** Active patient risk overview item. */
export interface ActivePatient {
  id: string;
  name: string;
  riskScore: number;
  riskLevel: 'HIGH' | 'MED' | 'LOW';
}

/** Agent status item. */
export interface AgentStatus {
  name: string;
  status: 'Active' | 'Degraded' | 'Inactive';
  alerts?: number;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, RouterModule, MatIconModule],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly signalR = inject(SignalRService);
  private readonly tasksApi = inject(EncounterTasksApiService);
  private readonly authService = inject(AuthService);

  private taskSub?: Subscription;
  private documentCreatedSub?: Subscription;
  
  // Reactive state using signals
  readonly encounterId = signal<string>('');
  readonly tasks = signal<AgentTaskResponse[]>([]);
  readonly isLoading = signal<boolean>(true);
  readonly isReconnecting = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);
  readonly adtPaused = signal<boolean>(false);

  // Wireframe data signals
  readonly currentUserName = signal<string>('Nancy');
  readonly lastUpdated = signal<string>(new Date().toLocaleTimeString());
  readonly adtEvents = signal<AdtEvent[]>([
    { id: '1', unit: 'A03', patient: 'Smith, J', event_type: 'Discharge', location: 'Unit 4W', time: '14:32' },
    { id: '2', unit: 'A01', patient: 'Patel, R', event_type: 'Admit', location: 'Unit 3N', time: '14:29' },
    { id: '3', unit: 'A02', patient: 'Nguyen, L', event_type: 'Transfer', location: '4W → ICU', time: '14:25' },
    { id: '4', unit: 'A01', patient: 'Garcia, M', event_type: 'Admit', location: 'Unit 3N', time: '14:18' },
    { id: '5', unit: 'A03', patient: 'Lee, K', event_type: 'Discharge', location: 'Unit 5E', time: '14:12' },
  ]);
  readonly activePatients = signal<ActivePatient[]>([
    { id: 'p1', name: 'Smith, John', riskScore: 0.82, riskLevel: 'HIGH' },
    { id: 'p2', name: 'Garcia, Maria', riskScore: 0.75, riskLevel: 'HIGH' },
    { id: 'p3', name: 'Patel, Rita', riskScore: 0.45, riskLevel: 'MED' },
    { id: 'p4', name: 'Nguyen, Lee', riskScore: 0.18, riskLevel: 'LOW' },
  ]);
  readonly agentStatusList = signal<AgentStatus[]>([
    { name: 'Transition Coordinator', status: 'Active' },
    { name: 'Documentation', status: 'Active' },
    { name: 'Medication Reconciliation', status: 'Degraded', alerts: 2 },
    { name: 'Bed Management', status: 'Active' },
    { name: 'Follow-up Care', status: 'Active' },
    { name: 'Patient Communications', status: 'Active' },
  ]);

  // Static mock tasks for wireframe preview
  readonly mockTasks = signal<AgentTaskResponse[]>([
    {
      id: 'task-1',
      encounter_id: 'enc-001',
      agent_type: 'medication_reconciliation',
      status: TaskStatus.PENDING,
      start_time: new Date().toISOString(),
      unit_id: '4-West',
      target_role: 'pharmacist',
      completed_time: null,
      payload: null,
      output: null,
    },
    {
      id: 'task-2',
      encounter_id: 'enc-002',
      agent_type: 'discharge_summary',
      status: TaskStatus.PENDING,
      start_time: new Date().toISOString(),
      unit_id: '3-North',
      target_role: 'physician',
      completed_time: null,
      payload: null,
      output: null,
    },
    {
      id: 'task-3',
      encounter_id: 'enc-003',
      agent_type: 'follow_up_care',
      status: TaskStatus.IN_PROGRESS,
      start_time: new Date().toISOString(),
      unit_id: 'ICU',
      target_role: 'nurse',
      completed_time: null,
      payload: null,
      output: null,
    },
  ]);

  readonly taskPriority = signal<Record<string, 'urgent' | 'critical' | 'normal'>>({
    'task-1': 'urgent',
    'task-2': 'critical',
    'task-3': 'normal',
  });

  readonly taskDisplayName = signal<Record<string, string>>({
    'medication_reconciliation': 'Medication Reconciliation',
    'discharge_summary': 'Discharge Summary Review',
    'follow_up_care': 'Follow-up Care Plan',
  });

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
    // Set current user name from auth service if available
    const user = this.authService.currentUser();
    if (user?.email) {
      this.currentUserName.set(user.email.split('@')[0]);
    }

    // Subscribe to document_created events and update queue count for physicians
    this.documentCreatedSub = this.signalR.documentCreated$.subscribe((payload) => {
      // Only update for physicians with PENDING_REVIEW documents
      if (
        payload.status === 'PENDING_REVIEW' &&
        this.authService.currentUser()?.role === 'physician'
      ) {
        // Document queue badge update placeholder
      }
    });

    // Extract encounter ID from route params
    this.route.params.subscribe(params => {
      const encounterId = params['encounterId'] || params['id'];
      if (encounterId) {
        this.encounterId.set(encounterId);
        this._initialize(encounterId);
      } else {
        // Wireframe mode: show dashboard with static mock data
        this.tasks.set(this.mockTasks());
        this.errorMessage.set(null);
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
    this.lastUpdated.set(new Date().toLocaleTimeString());
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

  /** Toggle ADT feed pause/resume. */
  toggleAdtFeed(): void {
    this.adtPaused.update(paused => !paused);
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
        roles: [currentUser.role],
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

  getPatientName(encounterId: string): string {
    const map: Record<string, string> = {
      'enc-001': 'Smith, John',
      'enc-002': 'Garcia, Maria',
      'enc-003': 'Nguyen, Lee',
    };
    return map[encounterId] || 'Unknown Patient';
  }

  getDueTime(startTime: string): string {
    const start = new Date(startTime);
    const now = new Date();
    const diffMs = now.getTime() - start.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    return `${diffHours}h ago`;
  }
}
