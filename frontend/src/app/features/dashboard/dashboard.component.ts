/**
 * DashboardComponent — Role-aware care team dashboard with real-time updates.
 *
 * Loads only APIs authorized for the current user's role, so bed managers,
 * pharmacists and other narrow roles never receive 401/403 on init.
 * Each card is actionable and deep-links to the screen where work is done.
 */
import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { Subscription, forkJoin, interval, Observable, of } from 'rxjs';
import { map } from 'rxjs/operators';

import { SignalRService, TaskUpdatedPayload, JoinGroupsRequest } from '../../core/signalr';
import { EncounterTasksApiService } from '../../core/api';
import {
  AgentTaskResponse,
  DASHBOARD_AGENTS,
  DASHBOARD_CARDS,
  DashboardCardConfig,
  TaskStatus,
  roleCanFetchDashboard,
  dashboardCardOrderForRole,
  quickLinksForRole,
  patientDetailTabForRole,
} from '../../core/models';
import { AuthService } from '../../core/auth/auth.service';
import { PatientApiService } from '../patients/services/patient-api.service';
import { PatientSummary } from '../patients/models/patient.model';
import { LiveAdtFeedComponent } from './components/live-adt-feed/live-adt-feed.component';
import { BedBoardService } from '../beds/services/bed-board.service';
import { BedDto, BedSuggestion } from '../beds/models/bed.model';
import { DocumentApiService, PendingDocument } from '../documents/services/document-api.service';
import { MedicationApiService, PharmacistAlert } from '../medications/services/medication-api.service';

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

/** Card-friendly bed census row. */
export interface BedCensusRow {
  label: string;
  count: number;
  icon: string;
  cssClass: string;
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
  private readonly router = inject(Router);
  private readonly signalR = inject(SignalRService);
  private readonly tasksApi = inject(EncounterTasksApiService);
  private readonly patientApi = inject(PatientApiService);
  private readonly bedBoardApi = inject(BedBoardService);
  private readonly documentApi = inject(DocumentApiService);
  private readonly medicationApi = inject(MedicationApiService);
  private readonly authService = inject(AuthService);

  private taskSub?: Subscription;
  private documentCreatedSub?: Subscription;
  private alertCreatedSub?: Subscription;
  private bedStatusSub?: Subscription;
  private bedSuggestionSub?: Subscription;
  private boardingAlertSub?: Subscription;
  private pollSub?: Subscription;
  private readonly POLL_INTERVAL_MS = 30_000;

  // Reactive state using signals
  readonly encounterId = signal<string>('');
  readonly tasks = signal<AgentTaskResponse[]>([]);
  readonly patients = signal<PatientSummary[]>([]);
  readonly beds = signal<BedDto[]>([]);
  readonly pendingSuggestions = signal<BedSuggestion[]>([]);
  readonly pendingApprovals = signal<PendingDocument[]>([]);
  readonly pharmacistAlerts = signal<PharmacistAlert[]>([]);
  readonly isLoading = signal<boolean>(true);
  readonly isReconnecting = signal<boolean>(false);
  readonly errorMessage = signal<string | null>(null);

  // User and timestamp signals
  readonly currentUserName = signal<string>('Nancy');
  readonly lastUpdated = signal<string>(new Date().toLocaleTimeString());

  /** Current user role in lowercase for RBAC checks. */
  readonly userRole = computed(() => this.authService.currentUser()?.role?.toLowerCase() ?? '');

  /** Permission helpers — never call an API the role cannot access. */
  readonly canFetchTasks = computed(() => roleCanFetchDashboard(this.userRole(), 'tasks'));
  readonly canFetchPatients = computed(() => roleCanFetchDashboard(this.userRole(), 'patients'));
  readonly canFetchBeds = computed(() => roleCanFetchDashboard(this.userRole(), 'beds'));
  readonly canFetchDocuments = computed(() => roleCanFetchDashboard(this.userRole(), 'documents'));
  readonly canFetchAlerts = computed(() => roleCanFetchDashboard(this.userRole(), 'alerts'));

  readonly visibleCards = computed<DashboardCardConfig[]>(() => {
    const role = this.userRole();
    const allowed = new Set(DASHBOARD_CARDS.filter(c => c.roles.includes(role)).map(c => c.id));
    return dashboardCardOrderForRole(role)
      .map(id => DASHBOARD_CARDS.find(c => c.id === id)!)
      .filter(c => allowed.has(c.id));
  });

  readonly quickLinks = computed(() => quickLinksForRole(this.userRole()));

  readonly taskPriority: Record<string, 'urgent' | 'critical' | 'normal'> = {
    'medication_reconciliation': 'urgent',
    'discharge_summary': 'critical',
    'follow_up_care': 'normal',
  };

  readonly taskDisplayName: Record<string, string> = {
    'medication_reconciliation': 'Medication Reconciliation',
    'discharge_summary': 'Discharge Summary Review',
    'follow_up_care': 'Follow-up Care Plan',
  };

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

  /** Live agent health derived from the current task list. */
  readonly agentStatusList = computed<AgentStatus[]>(() => {
    const tasks = this.tasks();
    return DASHBOARD_AGENTS.map(({ name, agentType }) => {
      const agentTasks = tasks.filter(t => t.agent_type?.toLowerCase() === agentType);
      if (agentTasks.length === 0) {
        return { name, status: 'Inactive' as const };
      }

      const issueCount = agentTasks.filter(t => {
        const status = t.status?.toUpperCase();
        return status === TaskStatus.FAILED || status === TaskStatus.BLOCKED || t.sla_breached === true;
      }).length;

      const hasActiveTask = agentTasks.some(t => {
        const status = t.status?.toUpperCase();
        return status === TaskStatus.IN_PROGRESS || status === 'RUNNING' || status === TaskStatus.PENDING;
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

  readonly bedCensusRows = computed<BedCensusRow[]>(() => {
    const all = this.beds();
    const byStatus = (status: string) => all.filter(b => b.status === status).length;
    return [
      { label: 'Occupied', count: byStatus('OCCUPIED'), icon: 'hotel', cssClass: 'occupied' },
      { label: 'Vacant', count: byStatus('VACANT'), icon: 'bed', cssClass: 'vacant' },
      { label: 'Dirty', count: byStatus('DIRTY'), icon: 'cleaning_services', cssClass: 'dirty' },
      { label: 'Maintenance', count: byStatus('MAINTENANCE'), icon: 'handyman', cssClass: 'maintenance' },
    ];
  });

  readonly edBoardingList = computed(() => this.pendingSuggestions());

  ngOnInit(): void {
    const user = this.authService.currentUser();
    if (user?.email) {
      this.currentUserName.set(user.email.split('@')[0]);
    }

    // Real-time cues: refresh the affected role-specific slice when an event arrives.
    this.documentCreatedSub = this.signalR.documentCreated$.subscribe((payload) => {
      if (this.canFetchDocuments() && payload.status === 'PENDING_REVIEW') {
        this._fetchPendingApprovals().subscribe(docs => this.pendingApprovals.set(docs));
      }
    });

    this.alertCreatedSub = this.signalR.alertCreated$.subscribe(() => {
      if (this.canFetchAlerts()) {
        this._fetchPharmacistAlerts().subscribe(alerts => this.pharmacistAlerts.set(alerts));
      }
    });

    this.bedStatusSub = this.signalR.bedStatusChanged$.subscribe(() => {
      if (this.canFetchBeds()) {
        this.bedBoardApi.getBeds().subscribe(beds => this.beds.set(beds));
        this._fetchPendingSuggestions();
      }
    });

    this.bedSuggestionSub = this.signalR.bedSuggestionCreated$.subscribe(() => {
      if (this.canFetchBeds()) {
        this._fetchPendingSuggestions();
      }
    });

    this.boardingAlertSub = this.signalR.boardingAlertCreated$.subscribe(() => {
      if (this.canFetchBeds()) {
        this._fetchPendingSuggestions();
      }
    });

    this.route.params.subscribe(params => {
      const encounterId = params['encounterId'] || params['id'] || '';
      this.encounterId.set(encounterId);
      void this._initialize(encounterId);
    });
  }

  ngOnDestroy(): void {
    this.taskSub?.unsubscribe();
    this.documentCreatedSub?.unsubscribe();
    this.alertCreatedSub?.unsubscribe();
    this.bedStatusSub?.unsubscribe();
    this.bedSuggestionSub?.unsubscribe();
    this.boardingAlertSub?.unsubscribe();
    this.pollSub?.unsubscribe();
    void this.signalR.disconnect();
  }

  /**
   * Refresh all authorized dashboard data manually.
   */
  refreshDashboard(): void {
    this.lastUpdated.set(new Date().toLocaleTimeString());
    void this._loadDashboardData();
  }

  /**
   * Navigate to the patient detail view, opening the tab most relevant to the current role.
   */
  goToPatient(encounterId: string, preferredTab?: string): void {
    const tab = preferredTab || patientDetailTabForRole(this.userRole());
    void this.router.navigate(['/patients', encounterId], { queryParams: { tab } });
  }

  goToTasks(encounterId?: string): void {
    if (encounterId) {
      void this.router.navigate(['/tasks'], { queryParams: { encounterId } });
    } else {
      void this.router.navigate(['/tasks']);
    }
  }

  goToDocuments(): void {
    void this.router.navigate(['/documents']);
  }

  goToMedications(): void {
    void this.router.navigate(['/medications']);
  }

  goToBedBoard(taskId?: string): void {
    if (taskId) {
      void this.router.navigate(['/beds'], { queryParams: { openAssign: taskId } });
    } else {
      void this.router.navigate(['/beds']);
    }
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

      await this._loadDashboardData();

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

  private _loadDashboardData(): Promise<void> {
    return new Promise((resolve, reject) => {
      const unit = this.authService.currentUser()?.units?.[0] ?? '';
      const encounterId = this.encounterId();

      const requests: Record<string, Observable<unknown>> = {};
      if (this.canFetchTasks()) {
        requests['tasks'] = encounterId
          ? this.tasksApi.getTasksForEncounter(encounterId)
          : this.tasksApi.getMyTasks();
      }
      if (this.canFetchPatients()) {
        requests['patients'] = this.patientApi.getPatients({ unit, page: 1, page_size: 100 });
      }
      if (this.canFetchBeds()) {
        requests['beds'] = this.bedBoardApi.getBeds();
        requests['pendingSuggestions'] = this.bedBoardApi.getSuggestions();
      }
      if (this.canFetchDocuments()) {
        requests['pendingApprovals'] = this._fetchPendingApprovals();
      }
      // Alerts are fetched after patients are known so we can scope them to visible encounters.

      // Edge case: a role with zero authorized data sources (should not happen) just resolves.
      if (Object.keys(requests).length === 0) {
        this.isLoading.set(false);
        resolve();
        return;
      }

      this.isLoading.set(true);
      forkJoin(requests).subscribe({
        next: (result: Record<string, unknown>) => {
          this.tasks.set((result['tasks'] as AgentTaskResponse[]) ?? this.tasks());
          this.patients.set((result['patients'] as { items?: PatientSummary[] })?.items ?? this.patients());
          this.beds.set((result['beds'] as BedDto[]) ?? this.beds());
          this.pendingSuggestions.set((result['pendingSuggestions'] as BedSuggestion[]) ?? this.pendingSuggestions());
          this.pendingApprovals.set((result['pendingApprovals'] as PendingDocument[]) ?? this.pendingApprovals());

          // Pharmacist alerts depend on the visible patient list, so load them after patients settle.
          if (this.canFetchAlerts()) {
            this._fetchPharmacistAlerts().subscribe(alerts => this.pharmacistAlerts.set(alerts));
          }

          this.isLoading.set(false);
          resolve();
        },
        error: error => {
          const message = this.#formatError(error);
          this.errorMessage.set(`Failed to load dashboard: ${message}`);
          this.isLoading.set(false);
          reject(error);
        }
      });
    });
  }

  private _fetchPendingApprovals(): Observable<PendingDocument[]> {
    if (!this.canFetchDocuments()) return of([]);
    return this.documentApi.getPendingReviewQueue();
  }

  private _fetchPharmacistAlerts(): Observable<PharmacistAlert[]> {
    if (!this.canFetchAlerts()) return of([]);
    // Bulk fetch all active alerts for the caller in a single request.
    return this.medicationApi.getAlerts('ACTIVE').pipe(
      map(response => response.alerts ?? [])
    );
  }

  private _fetchPendingSuggestions(): void {
    if (!this.canFetchBeds()) return;
    this.bedBoardApi.getSuggestions().subscribe({
      next: suggestions => this.pendingSuggestions.set(suggestions ?? []),
      error: error => console.error('Failed to fetch pending bed suggestions:', error),
    });
  }

  private _subscribeToTaskUpdates(): void {
    if (!this.canFetchTasks()) return;
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
    const taskId = event.task_id ?? event.taskId;
    const newStatus = event.new_status ?? event.newStatus;
    const completedAt = event.completed_at ?? event.completedAt ?? event.updated_at ?? event.updatedAt;

    if (!taskId || !newStatus) {
      console.warn('Received malformed task update event; ignoring.', event);
      return;
    }

    const currentTasks = this.tasks();
    const taskIndex = currentTasks.findIndex(t => t.id === taskId);

    if (taskIndex >= 0) {
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
   */
  private _startPolling(joinRequest: JoinGroupsRequest): void {
    this.pollSub?.unsubscribe();
    this.pollSub = interval(this.POLL_INTERVAL_MS).subscribe(() => {
      void this._loadDashboardData();
    });
  }

  getPatientName(encounterId: string): string {
    return this.patientNameMap()[encounterId] || 'Unknown Patient';
  }

  getDocumentPatientName(doc: PendingDocument): string {
    return doc.patientName || this.getPatientName(doc.encounterId);
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

  trackByCardId(_: number, card: DashboardCardConfig): string {
    return card.id;
  }

  #formatError(error: unknown): string {
    if (error && typeof error === 'object') {
      if ('error' in error && typeof (error as { error?: { detail?: string } }).error?.detail === 'string') {
        return (error as { error: { detail: string } }).error.detail;
      }
      if ('message' in error && typeof (error as { message?: string }).message === 'string') {
        return (error as { message: string }).message;
      }
    }
    return String(error);
  }
}
