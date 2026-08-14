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
import { Subscription, forkJoin, interval } from 'rxjs';

import { SignalRService, TaskUpdatedPayload, JoinGroupsRequest } from '../../core/signalr';
import { EncounterTasksApiService } from '../../core/api';
import { AgentTaskResponse, DASHBOARD_AGENTS, TaskStatus } from '../../core/models';
import { AuthService } from '../../core/auth/auth.service';
import { PatientApiService } from '../patients/services/patient-api.service';
import { PatientSummary } from '../patients/models/patient.model';
import { LiveAdtFeedComponent } from './components/live-adt-feed/live-adt-feed.component';

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
  imports: [CommonModule, RouterModule, MatIconModule, LiveAdtFeedComponent],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly signalR = inject(SignalRService);
  private readonly tasksApi = inject(EncounterTasksApiService);
  private readonly patientApi = inject(PatientApiService);
  private readonly authService = inject(AuthService);

  private taskSub?: Subscription;
  private documentCreatedSub?: Subscription;
  private pollSub?: Subscription;
  private readonly POLL_INTERVAL_MS = 30_000;
  
  // Reactive state using signals
  readonly encounterId = signal<string>('');
  readonly tasks = signal<AgentTaskResponse[]>([]);
  readonly isLoading = signal<boolean>(true);
  readonly isReconnecting = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  // User and timestamp signals
  readonly currentUserName = signal<string>('Nancy');
  readonly lastUpdated = signal<string>(new Date().toLocaleTimeString());

  // Live data signals
  readonly patients = signal<PatientSummary[]>([]);
  /** Live agent health derived from the current task list. */
  readonly agentStatusList = computed<AgentStatus[]>(() => {
    const tasks = this.tasks();
    return DASHBOARD_AGENTS.map(({ name, agentType }) => {
      const agentTasks = tasks.filter(
        t => t.agent_type?.toLowerCase() === agentType,
      );
      if (agentTasks.length === 0) {
        return { name, status: 'Inactive' as const };
      }

      const issueCount = agentTasks.filter(t => {
        const status = t.status?.toUpperCase();
        return (
          status === TaskStatus.FAILED ||
          status === TaskStatus.BLOCKED ||
          t.sla_breached === true
        );
      }).length;

      // Active if at least one task is in progress/running and there are no issues.
      const hasActiveTask = agentTasks.some(t => {
        const status = t.status?.toUpperCase();
        return (
          status === TaskStatus.IN_PROGRESS ||
          status === 'RUNNING' ||
          status === TaskStatus.PENDING
        );
      });

      if (issueCount > 0) {
        return { name, status: 'Degraded' as const, alerts: issueCount };
      }
      if (hasActiveTask) {
        return { name, status: 'Active' as const };
      }
      return { name, status: 'Inactive' as const };
    });
  });

  readonly taskPriority = signal<Record<string, 'urgent' | 'critical' | 'normal'>>({
    'medication_reconciliation': 'urgent',
    'discharge_summary': 'critical',
    'follow_up_care': 'normal',
  });

  readonly taskDisplayName = signal<Record<string, string>>({
    'medication_reconciliation': 'Medication Reconciliation',
    'discharge_summary': 'Discharge Summary Review',
    'follow_up_care': 'Follow-up Care Plan',
  });

  /** Map encounter_id → "Last, First" for task subtitles. */
  readonly patientNameMap = computed<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    for (const p of this.patients()) {
      map[p.encounter_id] = `${p.last_name}, ${p.first_name}`;
    }
    return map;
  });

  /** Active patients derived from the live patient list. */
  readonly activePatients = computed<ActivePatient[]>(() =>
    this.patients().map(p => ({
      id: p.encounter_id,
      name: `${p.first_name} ${p.last_name}`,
      riskScore: p.risk_score ?? this._defaultRiskScore(p.risk_tier),
      riskLevel: this._riskTierToLevel(p.risk_tier),
    }))
  );

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

    // Extract optional encounter ID from route params, then load live data
    this.route.params.subscribe(params => {
      const encounterId = params['encounterId'] || params['id'] || '';
      this.encounterId.set(encounterId);
      void this._initialize(encounterId);
    });
  }

  ngOnDestroy(): void {
    this.taskSub?.unsubscribe();
    this.documentCreatedSub?.unsubscribe();
    this.pollSub?.unsubscribe();
    void this.signalR.disconnect();
  }

  /**
   * Refresh tasks and patients manually — useful when user suspects stale data.
   */
  refreshTasks(): void {
    const encounterId = this.encounterId();
    this.lastUpdated.set(new Date().toLocaleTimeString());

    this.isLoading.set(true);
    this.errorMessage.set(null);

    const unit = this.authService.currentUser()?.units?.[0] ?? '';
    forkJoin({
      tasks: encounterId
        ? this.tasksApi.getTasksForEncounter(encounterId)
        : this.tasksApi.getMyTasks(),
      patients: this.patientApi.getPatients({ unit, page: 1, page_size: 100 }),
    }).subscribe({
      next: ({ tasks, patients }) => {
        this.tasks.set(tasks);
        this.patients.set(patients.items ?? []);
        this.isLoading.set(false);
      },
      error: error => {
        this.errorMessage.set(`Failed to refresh dashboard: ${error.message}`);
        this.isLoading.set(false);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private async _initialize(encounterId: string): Promise<void> {
    try {
      this.isLoading.set(true);
      this.errorMessage.set(null);
      this.lastUpdated.set(new Date().toLocaleTimeString());

      const currentUser = this.authService.currentUser();
      if (!currentUser) {
        throw new Error('User not authenticated');
      }

      // 1. Load tasks and patients in parallel
      await this._loadDashboardData(encounterId, currentUser);

      // 2. Start SignalR connection with group subscriptions (best-effort)
      //    Local development does not run Azure SignalR Service, so a missing
      //    hub is expected. We degrade to REST polling instead of failing init.
      const joinRequest: JoinGroupsRequest = {
        units: currentUser.units || [],
        roles: [currentUser.role],
      };

      try {
        await this.signalR.connect(joinRequest);
        this._subscribeToTaskUpdates();
      } catch (signalrError) {
        console.warn('SignalR real-time hub unavailable; falling back to polling:', signalrError);
        this._startPolling(joinRequest);
      }

      this.isLoading.set(false);
    } catch (error) {
      this.errorMessage.set(`Failed to initialize dashboard: ${error}`);
      this.isLoading.set(false);
    }
  }

  private async _loadDashboardData(encounterId: string, currentUser: { role: string; units?: string[] }): Promise<void> {
    return new Promise((resolve, reject) => {
      const unit = currentUser.units?.[0] ?? '';
      forkJoin({
        tasks: encounterId
          ? this.tasksApi.getTasksForEncounter(encounterId)
          : this.tasksApi.getMyTasks(),
        patients: this.patientApi.getPatients({ unit, page: 1, page_size: 100 }),
      }).subscribe({
        next: ({ tasks, patients }) => {
          this.tasks.set(tasks);
          this.patients.set(patients.items ?? []);
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
    // Backend broadcasts snake_case fields (task_id, new_status, updated_at);
    // some older client code uses camelCase aliases. Normalize both.
    const taskId = event.task_id ?? event.taskId;
    const newStatus = event.new_status ?? event.newStatus;
    const completedAt =
      event.completed_at ?? event.completedAt ?? event.updated_at ?? event.updatedAt;

    if (!taskId || !newStatus) {
      console.warn('Received malformed task update event; ignoring.', event);
      return;
    }

    const currentTasks = this.tasks();
    const taskIndex = currentTasks.findIndex(t => t.id === taskId);

    if (taskIndex >= 0) {
      // Update existing task
      const updatedTasks = [...currentTasks];
      updatedTasks[taskIndex] = {
        ...updatedTasks[taskIndex],
        status: newStatus,
        completed_time:
          newStatus.toUpperCase() === 'COMPLETED'
            ? completedAt || new Date().toISOString()
            : updatedTasks[taskIndex].completed_time,
      };
      this.tasks.set(updatedTasks);
    } else {
      // New task arrived — fetch full details from API
      this.tasksApi.getTaskById(taskId).subscribe({
        next: task => {
          this.tasks.set([...this.tasks(), task]);
        },
        error: error => {
          console.error(`Failed to fetch new task ${taskId}:`, error);
        }
      });
    }
  }

  /**
   * REST fallback for real-time updates when SignalR hub is unavailable.
   * Refreshes tasks and patients on a fixed interval without blocking the UI.
   */
  private _startPolling(joinRequest: JoinGroupsRequest): void {
    this.pollSub?.unsubscribe();
    this.pollSub = interval(this.POLL_INTERVAL_MS).subscribe(() => {
      const encounterId = this.encounterId();
      const currentUser = this.authService.currentUser();
      if (!currentUser) return;

      const unit = currentUser.units?.[0] ?? '';
      forkJoin({
        tasks: encounterId
          ? this.tasksApi.getTasksForEncounter(encounterId)
          : this.tasksApi.getMyTasks(),
        patients: this.patientApi.getPatients({ unit, page: 1, page_size: 100 }),
      }).subscribe({
        next: ({ tasks, patients }) => {
          this.tasks.set(tasks);
          this.patients.set(patients.items ?? []);
          this.lastUpdated.set(new Date().toLocaleTimeString());
        },
        error: error => {
          console.error('Dashboard polling refresh failed:', error);
        }
      });
    });
  }

  getPatientName(encounterId: string): string {
    return this.patientNameMap()[encounterId] || 'Unknown Patient';
  }

  private _riskTierToLevel(tier: string): ActivePatient['riskLevel'] {
    switch (tier?.toUpperCase()) {
      case 'HIGH':
        return 'HIGH';
      case 'MEDIUM':
        return 'MED';
      case 'LOW':
        return 'LOW';
      default:
        return 'LOW';
    }
  }

  private _defaultRiskScore(tier: string): number {
    switch (tier?.toUpperCase()) {
      case 'HIGH':
        return 0.82;
      case 'MEDIUM':
        return 0.45;
      case 'LOW':
        return 0.18;
      default:
        return 0;
    }
  }

  getDueTime(startTime: string | null | undefined): string {
    if (!startTime) return '—';
    const start = new Date(startTime);
    if (isNaN(start.getTime())) return '—';
    const now = new Date();
    const diffMs = now.getTime() - start.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    return `${diffHours}h ago`;
  }

  getPriorityLabel(priority: 'urgent' | 'critical' | 'normal' | undefined): string {
    const labels: Record<string, string> = {
      urgent: 'URGENT',
      critical: 'CRITICAL',
      normal: 'NORMAL',
    };
    return labels[priority ?? 'normal'] ?? 'NORMAL';
  }

  getRiskLabel(level: ActivePatient['riskLevel']): string {
    const labels: Record<string, string> = {
      HIGH: 'HIGH',
      MED: 'MED',
      LOW: 'LOW',
    };
    return labels[level] ?? level;
  }

}
