import { Component, signal, inject, computed, effect, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { Subscription } from 'rxjs';
import {
  AlertActionDialogComponent,
  AlertActionDialogData,
} from './alert-action-dialog.component';
import {
  CarePlanDialogComponent,
  CarePlanSection,
} from './care-plan-dialog.component';
import {
  DocumentApprovalDialogComponent,
  DocumentApprovalDialogData,
} from './document-approval-dialog.component';
import { ToastService } from '@core/notifications/toast.service';
import { EncounterTasksApiService } from '@core/api';
import { AgentTaskResponse, AGENT_TYPE_DISPLAY_NAME, PATIENT_DETAIL_TAB_ROLES, TaskStatus, roleCanFetchPatientDetail } from '@core/models';
import { AuthService } from '@core/auth/auth.service';
import { PatientApiService } from '../../services/patient-api.service';
import { DocumentApiService, BackendDocument } from '@features/documents/services/document-api.service';
import { DocumentService } from '@features/documents/services/document.service';
import { TimelineApiService, TimelineEvent as BackendTimelineEvent } from '../../services/timeline-api.service';
import {
  MedicationAnalysisResponse,
  MedicationApiService,
  MedicationHistoryEncounter,
  MedicationHistoryResponse,
  MedicationReconciliationResponse,
  MedicationReconciliationResult,
  PharmacistAlert,
} from '@features/medications/services/medication-api.service';

interface PatientDetailViewModel {
  name: string;
  mrn: string;
  mrnMasked: string;
  dob: string;
  age: number;
  unit: string;
  room: string;
  bed: string;
  admissionDate: string;
  attending: string;
  riskScore: number;
  riskLevel: 'HIGH' | 'MED' | 'LOW' | string;
}

interface AlertItem {
  id: string;
  type: 'critical' | 'warning';
  title: string;
  text: string;
  link: string;
  dialog: AlertActionDialogData;
}

interface AgentTaskView {
  name: string;
  status: 'ok' | 'warn' | 'pending';
  label: string;
}

interface RiskFactor {
  text: string;
}

interface OpenTask {
  id: string;
  title: string;
  meta: string;
  owner: string;
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  done: boolean;
}

interface TimelineEvent {
  time: string;
  title: string;
  desc: string;
  type: string;
  rawTimestamp: string | null;
  eventType: string;
  status: string | null;
  resourceType: string | null;
  resourceId: string | null;
  metadata: Record<string, unknown>;
}

/**
 * Patient Detail Component — matches Hi-Fi wireframe SCR-004.
 */
@Component({
  selector: 'app-patient-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatIconModule,
    MatButtonModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatDialogModule,
  ],
  templateUrl: './patient-detail.component.html',
  styleUrl: './patient-detail.component.scss',
})
export class PatientDetailComponent implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly toast = inject(ToastService);
  private readonly patientApi = inject(PatientApiService);
  private readonly tasksApi = inject(EncounterTasksApiService);
  private readonly documentApi = inject(DocumentApiService);
  private readonly documentService = inject(DocumentService);
  private readonly medicationApi = inject(MedicationApiService);
  private readonly timelineApi = inject(TimelineApiService);
  private readonly auth = inject(AuthService);

  private taskUpdateSub?: Subscription;

  readonly activeTab = signal<string>('Overview');
  readonly allTabs = ['Overview', 'Medications', 'Documents', 'Tasks', 'Timeline'] as const;
  readonly patientId = signal<string>('enc-001');

  /** Current user role in lowercase, reactive to real-time role switches. */
  readonly userRole = computed(() => this.auth.currentUser()?.role?.toLowerCase() ?? '');

  /** Tabs visible to the current role, derived from the RBAC matrix. */
  readonly visibleTabs = computed<string[]>(() => {
    const role = this.userRole();
    return this.allTabs.filter((tab) => PATIENT_DETAIL_TAB_ROLES[tab]?.includes(role));
  });

  /** When the active tab becomes hidden (e.g. after role switch), fall back to Overview. */
  readonly safeActiveTab = computed<string>(() => {
    const active = this.activeTab();
    return this.visibleTabs().includes(active) ? active : (this.visibleTabs()[0] ?? 'Overview');
  });

  /** Keep the active tab in sync with role-driven visibility changes. */
  private readonly activeTabSync = effect(() => {
    const safe = this.safeActiveTab();
    if (this.activeTab() !== safe) {
      this.activeTab.set(safe);
    }
  });

  readonly mrnRevealed = signal<boolean>(false);

  readonly patient = signal<PatientDetailViewModel>({
    name: 'Loading…',
    mrn: '●●●●●●',
    mrnMasked: '●●●●●●',
    dob: '',
    age: 0,
    unit: '',
    room: '',
    bed: '',
    admissionDate: '',
    attending: '',
    riskScore: 0,
    riskLevel: 'LOW',
  });

  readonly agentTaskResponses = signal<AgentTaskResponse[]>([]);
  readonly isLoadingAgentTasks = signal<boolean>(false);
  readonly agentTaskError = signal<string | null>(null);
  readonly selectedAgentTaskId = signal<string | null>(null);

  readonly agentTasks = computed<AgentTaskView[]>(() => {
    const tasks = this.agentTaskResponses();
    if (tasks.length === 0) {
      const alertCount = this.activeAlertCount();
      return [
        { name: 'Transition Coordinator', status: 'ok', label: 'Complete' },
        { name: 'Documentation Agent', status: 'ok', label: 'Draft ready' },
        {
          name: 'Medication Reconciliation',
          status: alertCount > 0 ? 'warn' : 'ok',
          label: alertCount > 0 ? `⚠ ${alertCount} alert${alertCount === 1 ? '' : 's'}` : 'Complete',
        },
        { name: 'Bed Management', status: 'ok', label: 'Assigned' },
        { name: 'Follow-up Care', status: 'pending', label: '● Pending' },
        { name: 'Patient Communications', status: 'ok', label: 'Active' },
      ];
    }

    return tasks.map((task) => {
      const status = task.status?.toUpperCase();
      let viewStatus: AgentTaskView['status'] = 'pending';
      let label = task.status ?? 'Pending';

      if (status === TaskStatus.COMPLETED) {
        viewStatus = 'ok';
        label = 'Complete';
      } else if (status === TaskStatus.FAILED || status === TaskStatus.BLOCKED) {
        viewStatus = 'warn';
        label = task.status ?? 'Failed';
      } else if (status === TaskStatus.IN_PROGRESS) {
        viewStatus = 'pending';
        label = 'In Progress';
      } else if (status === TaskStatus.PENDING) {
        viewStatus = 'pending';
        label = 'Pending';
      }

      return {
        name: this.agentDisplayName(task.agent_type),
        status: viewStatus,
        label,
      };
    });
  });

  readonly selectedAgentTask = computed<AgentTaskResponse | null>(() => {
    const id = this.selectedAgentTaskId();
    if (!id) {
      return null;
    }
    return this.agentTaskResponses().find((t) => t.id === id) ?? null;
  });

  readonly agentTaskColumns = [
    'agentType',
    'status',
    'startedAt',
    'completedAt',
    'actions',
  ];

  readonly medicationDisplayedColumns = [
    'name',
    'schedule',
    'phases',
    'severity',
    'actions',
  ];

  readonly documents = signal<BackendDocument[]>([]);
  readonly isLoadingDocuments = signal<boolean>(false);
  readonly documentError = signal<string | null>(null);
  readonly selectedAgentRole = signal<string>('documentation');
  readonly isGeneratingDocument = signal<boolean>(false);
  readonly documentGenerationError = signal<string | null>(null);

  readonly agentRoleOptions = [
    { value: 'documentation', label: 'Documentation Agent', documentType: 'Discharge Summary' },
    { value: 'medication_reconciliation', label: 'Medication Reconciliation Agent', documentType: 'Medication Reconciliation Report' },
    { value: 'follow_up_care', label: 'Follow-up Care Agent', documentType: 'Follow-up Care Plan' },
    { value: 'patient_communication', label: 'Patient Communication Agent', documentType: 'Patient Instructions' },
    { value: 'bed_management', label: 'Bed Management Agent', documentType: 'Transfer Summary' },
    { value: 'coordinator', label: 'Transition Coordinator Agent', documentType: 'Care Transition Summary' },
  ];

  readonly medications = signal<MedicationReconciliationResponse | null>(null);
  readonly isLoadingMedications = signal<boolean>(false);
  readonly medicationError = signal<string | null>(null);
  readonly medicationPending = signal<boolean>(false);
  readonly expandedMedId = signal<string | null>(null);
  readonly showHistory = signal<boolean>(false);
  readonly medicationHistory = signal<MedicationHistoryResponse | null>(null);
  readonly isLoadingHistory = signal<boolean>(false);
  readonly historyError = signal<string | null>(null);
  readonly aiAnalysis = signal<MedicationAnalysisResponse | null>(null);
  readonly isLoadingAiAnalysis = signal<boolean>(false);
  readonly aiAnalysisError = signal<string | null>(null);

  readonly pharmacistAlerts = signal<PharmacistAlert[]>([]);
  readonly isLoadingAlerts = signal<boolean>(false);
  readonly alertError = signal<string | null>(null);

  readonly pendingApprovals = computed(() => {
    return this.documents().filter((d) => d.status === 'PENDING_REVIEW');
  });

  readonly pendingApprovalCount = computed(() => this.pendingApprovals().length);

  readonly alerts = computed<AlertItem[]>(() => {
    return this.pharmacistAlerts()
      .filter((alert) => alert.status === 'ACTIVE')
      .map((alert) => this.mapAlertToItem(alert));
  });

  readonly activeAlertCount = computed(() => this.alerts().length);

  readonly riskFactors = signal<RiskFactor[]>([
    { text: 'History of CHF readmission within 30 days' },
    { text: 'No primary care follow-up scheduled' },
    { text: 'Complex medication regimen (8+ meds)' },
    { text: 'Social determinants: transportation barrier' },
  ]);

  readonly openTasks = signal<OpenTask[]>([
    { id: 't1', title: 'Confirm follow-up appointment', meta: 'Primary care within 7 days', owner: 'Transition', priority: 'HIGH', done: false },
    { id: 't2', title: 'Review warfarin + aspirin interaction', meta: 'Major bleed risk', owner: 'Pharmacy', priority: 'HIGH', done: false },
    { id: 't3', title: 'Arrange transportation', meta: 'Wheelchair van requested', owner: 'Social Work', priority: 'MEDIUM', done: false },
  ]);

  readonly completedTasks = signal<OpenTask[]>([
    { id: 't4', title: 'Admission reconciliation', meta: 'Completed on admission', owner: 'Nursing', priority: 'MEDIUM', done: true },
    { id: 't5', title: 'Discharge summary draft', meta: 'AI draft generated', owner: 'Doc Agent', priority: 'LOW', done: true },
  ]);

  readonly timelineEvents = signal<TimelineEvent[]>([]);
  readonly isLoadingTimeline = signal<boolean>(false);
  readonly timelineError = signal<string | null>(null);

  ngOnInit(): void {
    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (patientId) {
      this.patientId.set(patientId);
      const role = this.userRole();
      this.loadPatient(patientId);
      if (roleCanFetchPatientDetail(role, 'tasks')) {
        this.loadAgentTasks(patientId);
      }
      if (roleCanFetchPatientDetail(role, 'documents')) {
        this.loadDocuments(patientId);
      }
      if (roleCanFetchPatientDetail(role, 'medications')) {
        this.loadMedications(patientId);
      }
      if (roleCanFetchPatientDetail(role, 'alerts')) {
        this.loadPharmacistAlerts(patientId);
      }
      if (roleCanFetchPatientDetail(role, 'timeline')) {
        this.loadTimeline(patientId);
      }
    }

    // Restore the tab requested by a returning child view (e.g. document review).
    const returnTab = this.route.snapshot.queryParamMap.get('tab');
    const matchedTab = this.visibleTabs().find(
      (t) => t.toLowerCase() === returnTab?.toLowerCase(),
    );
    if (matchedTab) {
      this.activeTab.set(matchedTab);
    }

    // Sync active tab when landing directly on a child route.
    const urlSegments = this.route.snapshot.url.map((s) => s.path);
    const lastSegment = urlSegments[urlSegments.length - 1];
    if (lastSegment === 'medications') {
      this.activeTab.set('Medications');
    } else if (lastSegment === 'documents') {
      this.activeTab.set('Documents');
    }
  }

  ngOnDestroy(): void {
    this.taskUpdateSub?.unsubscribe();
  }

  private loadPatient(encounterId: string): void {
    this.patientApi.getPatientByEncounter(encounterId).subscribe({
      next: (data) => {
        this.patient.set({
          name: `${data.last_name}, ${data.first_name}`,
          mrn: data.mrn_masked || '●●●●●●',
          mrnMasked: data.mrn_masked || '●●●●●●',
          dob: data.date_of_birth || '',
          age: this.computeAge(data.date_of_birth),
          unit: data.current_unit || '',
          room: data.room_number || '',
          bed: data.room_number || '',
          admissionDate: data.admission_date ? data.admission_date.split('T')[0] : '',
          attending: '—',
          riskScore: data.risk_score ?? 0,
          riskLevel: (data.risk_tier as PatientDetailViewModel['riskLevel']) || 'LOW',
        });
      },
      error: () => {
        // Keep static fallback preview if backend detail endpoint is unavailable
      },
    });
  }

  private computeAge(dob: string | undefined): number {
    if (!dob) return 0;
    const birth = new Date(dob);
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    const monthDiff = today.getMonth() - birth.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
      age--;
    }
    return age;
  }

  private loadAgentTasks(encounterId: string): void {
    this.isLoadingAgentTasks.set(true);
    this.agentTaskError.set(null);
    this.tasksApi.getTasksForEncounter(encounterId).subscribe({
      next: (response) => {
        const tasks = Array.isArray(response) ? response : (response as any)?.tasks ?? [];
        this.agentTaskResponses.set(tasks);
        this.isLoadingAgentTasks.set(false);
      },
      error: (err: Error) => {
        this.agentTaskError.set(err.message);
        this.isLoadingAgentTasks.set(false);
      },
    });
  }

  private loadDocuments(encounterId: string): void {
    this.isLoadingDocuments.set(true);
    this.documentError.set(null);
    this.documentApi.getDocumentsByEncounter(encounterId).subscribe({
      next: (docs) => {
        this.documents.set(docs);
        this.isLoadingDocuments.set(false);
      },
      error: (err: Error) => {
        this.documentError.set(err.message);
        this.isLoadingDocuments.set(false);
      },
    });
  }

  private loadMedications(encounterId: string): void {
    this.isLoadingMedications.set(true);
    this.medicationError.set(null);
    this.medicationPending.set(false);
    this.medicationApi.getReconciliation(encounterId).subscribe({
      next: (data) => {
        // FastAPI returns 202 with body { detail: { status: 'pending', message: ... } }
        // before medication reconciliation has been generated.
        const pending = (data as any).detail?.status === 'pending';
        if (pending) {
          this.medicationPending.set(true);
        } else {
          this.medications.set(data as MedicationReconciliationResponse);
        }
        this.isLoadingMedications.set(false);
      },
      error: (err: any) => {
        this.medicationError.set(err.message ?? 'Failed to load medications');
        this.isLoadingMedications.set(false);
      },
    });
  }

  generateMedications(): void {
    const encounterId = this.patientId();
    if (!encounterId) {
      return;
    }
    this.isLoadingMedications.set(true);
    this.medicationPending.set(false);
    this.medicationError.set(null);
    this.medicationApi.generateReconciliation(encounterId).subscribe({
      next: (data) => {
        this.medications.set(data);
        this.isLoadingMedications.set(false);
      },
      error: (err: Error) => {
        this.medicationError.set(err.message ?? 'Failed to generate medications');
        this.isLoadingMedications.set(false);
      },
    });
  }

  private loadMedicationHistory(encounterId: string): void {
    this.isLoadingHistory.set(true);
    this.historyError.set(null);
    this.medicationApi.getMedicationHistory(encounterId).subscribe({
      next: (data) => {
        this.medicationHistory.set(data);
        this.isLoadingHistory.set(false);
      },
      error: (err: Error) => {
        this.historyError.set(err.message ?? 'Failed to load medication history');
        this.isLoadingHistory.set(false);
      },
    });
  }

  toggleShowHistory(): void {
    const next = !this.showHistory();
    this.showHistory.set(next);
    if (next && !this.medicationHistory()) {
      const encounterId = this.patientId();
      if (encounterId) {
        this.loadMedicationHistory(encounterId);
      }
    }
  }

  refreshHistory(): void {
    const encounterId = this.patientId();
    if (encounterId) {
      this.loadMedicationHistory(encounterId);
    }
  }

  toggleMedDetail(med: MedicationReconciliationResult): void {
    this.expandedMedId.update((id) => (id === med.id ? null : med.id));
  }

  showDetailRow = (_index: number, _row: MedicationReconciliationResult): boolean => true;

  analyzeMedicationChanges(): void {
    const encounterId = this.patientId();
    if (!encounterId) {
      return;
    }

    this.isLoadingAiAnalysis.set(true);
    this.aiAnalysisError.set(null);
    this.aiAnalysis.set(null);

    this.medicationApi.analyzeMedications(encounterId).subscribe({
      next: (analysis) => {
        this.aiAnalysis.set(analysis);
        this.isLoadingAiAnalysis.set(false);
      },
      error: (err: Error) => {
        this.aiAnalysisError.set(err.message ?? 'Failed to generate AI analysis');
        this.isLoadingAiAnalysis.set(false);
      },
    });
  }

  medicationCategoryClass(category: string | null | undefined): string {
    switch (category?.toUpperCase()) {
      case 'CONTINUED':
        return 'category-continued';
      case 'NEW':
        return 'category-new';
      case 'STOPPED':
        return 'category-stopped';
      case 'DOSE_CHANGED':
        return 'category-dose-changed';
      default:
        return 'category-unknown';
    }
  }

  readonly selectedMedication = computed<MedicationReconciliationResult | null>(() => {
    const id = this.expandedMedId();
    if (!id) {
      return null;
    }
    return this.medications()?.medications?.find((m) => m.id === id) ?? null;
  });

  readonly latestHistoryEncounter = computed<MedicationHistoryEncounter | null>(() => {
    const history = this.medicationHistory()?.history ?? [];
    return history[0] ?? null;
  });

  readonly medicationChanges = computed(() => {
    const currentMeds = this.medications()?.medications ?? [];
    const prior = this.latestHistoryEncounter();
    const priorMeds = prior?.medications ?? [];

    const priorByName = new Map(priorMeds.map((m) => [m.name.toLowerCase(), m]));
    const currentByName = new Map(currentMeds.map((m) => [m.name.toLowerCase(), m]));

    const continued: { current: MedicationReconciliationResult; prior: MedicationReconciliationResult; doseChanged: boolean }[] = [];
    const newMeds: MedicationReconciliationResult[] = [];

    for (const med of currentMeds) {
      const priorMed = priorByName.get(med.name.toLowerCase());
      if (priorMed) {
        continued.push({
          current: med,
          prior: priorMed,
          doseChanged: med.dose !== priorMed.dose,
        });
      } else {
        newMeds.push(med);
      }
    }

    const stopped = priorMeds.filter((m) => !currentByName.has(m.name.toLowerCase()));

    return { continued, new: newMeds, stopped, priorEncounter: prior };
  });

  readonly doseChangedCount = computed(() =>
    this.medicationChanges().continued.filter((c) => c.doseChanged).length
  );

  private loadPharmacistAlerts(encounterId: string): void {
    this.isLoadingAlerts.set(true);
    this.alertError.set(null);
    this.medicationApi.getEncounterAlerts(encounterId).subscribe({
      next: (alerts) => {
        this.pharmacistAlerts.set(alerts);
        this.isLoadingAlerts.set(false);
      },
      error: (err: Error) => {
        this.alertError.set(err.message);
        this.isLoadingAlerts.set(false);
      },
    });
  }

  private loadTimeline(encounterId: string): void {
    this.isLoadingTimeline.set(true);
    this.timelineError.set(null);
    this.timelineApi.getEncounterTimeline(encounterId).subscribe({
      next: (response) => {
        const events = (response.events ?? []).map((e) => this.toViewTimelineEvent(e));
        this.timelineEvents.set(events);
        this.isLoadingTimeline.set(false);
      },
      error: (err: Error) => {
        this.timelineError.set(err.message ?? 'Failed to load timeline');
        this.isLoadingTimeline.set(false);
      },
    });
  }

  private toViewTimelineEvent(event: BackendTimelineEvent): TimelineEvent {
    const timestamp = event.timestamp ? new Date(event.timestamp) : null;
    const time = timestamp
      ? timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : '—';
    const date = timestamp
      ? timestamp.toLocaleDateString([], { month: 'short', day: 'numeric' })
      : null;
    const displayTime = date ? `${date} · ${time}` : time;

    return {
      time: displayTime,
      title: event.title,
      desc: event.description ?? '',
      type: this.mapTimelineEventType(event.event_type),
      rawTimestamp: event.timestamp,
      eventType: event.event_type,
      status: event.status,
      resourceType: event.resource_type,
      resourceId: event.resource_id,
      metadata: event.metadata,
    };
  }

  private mapTimelineEventType(eventType: string): string {
    switch (eventType?.toLowerCase()) {
      case 'admission':
      case 'encounter_created':
        return 'admission';
      case 'transfer':
        return 'transfer';
      case 'discharge':
        return 'discharge';
      case 'cancellation':
        return 'cancellation';
      case 'document':
      case 'approval':
        return 'success';
      case 'rejection':
        return 'alert';
      case 'alert':
      case 'medication':
        return 'warning';
      case 'agent_task':
        return 'system';
      case 'resolution':
        return 'success';
      default:
        return 'system';
    }
  }

  private mapAlertToItem(alert: PharmacistAlert): AlertItem {
    const title = alert.drug_pair?.length
      ? `Major Drug Interaction: ${alert.drug_pair.join(' + ')}`
      : alert.alert_type === 'CHRONIC_MEDICATION_MISSING'
        ? 'Chronic Medication Missing'
        : 'Pharmacist Alert';

    const text = alert.interaction_description ?? 'Review before discharge.';

    return {
      id: alert.id,
      type: alert.severity === 'HIGH' ? 'critical' : 'warning',
      title,
      text,
      link: 'Resolve →',
      dialog: {
        title: `Resolve ${title}`,
        severity: alert.severity,
        risk: alert.interaction_description ?? '',
        description: text,
        checklist: [
          'Review clinical context and patient history',
          'Confirm management plan with prescriber if needed',
          'Document resolution reason',
        ],
        confirmLabel: 'Mark Resolved',
      },
    };
  }

  documentDisplayTitle(doc: BackendDocument): string {
    const type = doc.document_type;
    return type
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  documentStatusLabel(status: string): string {
    switch (status?.toUpperCase()) {
      case 'PENDING_REVIEW':
      case 'PENDING_APPROVAL':
        return 'Pending Review';
      case 'APPROVED':
        return 'Approved';
      case 'REJECTED':
        return 'Rejected';
      case 'DRAFT':
        return 'Draft';
      default:
        return status;
    }
  }

  isDocumentApproved(doc: BackendDocument): boolean {
    return doc.status?.toUpperCase() === 'APPROVED';
  }

  isDocumentRejected(doc: BackendDocument): boolean {
    return doc.status?.toUpperCase() === 'REJECTED';
  }

  isDocumentReviewable(doc: BackendDocument): boolean {
    const s = doc.status?.toUpperCase();
    return s === 'DRAFT' || s === 'PENDING_APPROVAL' || s === 'PENDING_REVIEW';
  }

  canRegenerateDocument(doc: BackendDocument): boolean {
    return !this.isDocumentApproved(doc);
  }

  canGenerateDocumentForRole(agentRole: string): boolean {
    const targetType = this.documentTypeForAgentRole(agentRole);
    if (!targetType) {
      return true;
    }
    // Block Generate when any document of this type already exists.
    // Existing drafts/pending/rejected documents must use Regenerate;
    // approved documents cannot be regenerated.
    return !this.documents().some((d) => d.document_type === targetType);
  }

  private documentTypeForAgentRole(agentRole: string): string | null {
    const map: Record<string, string> = {
      documentation: 'discharge_summary',
      medication_reconciliation: 'medication_reconciliation',
      follow_up_care: 'follow_up_plan',
      patient_communication: 'patient_instructions',
      bed_management: 'transfer_summary',
      coordinator: 'care_transition_summary',
    };
    return map[agentRole] ?? null;
  }

  agentDisplayName(agentType: string | null): string {
    if (!agentType) {
      return 'Unknown';
    }
    return AGENT_TYPE_DISPLAY_NAME[agentType.toLowerCase()] ?? agentType;
  }

  agentStatusClass(status: string | null): string {
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

  selectAgentTask(task: AgentTaskResponse): void {
    this.selectedAgentTaskId.set(task.id);
  }

  setTab(tab: string): void {
    this.activeTab.set(tab);

    // All tabs now render in-place within the patient detail page while
    // preserving the patient header. Only the active tab query param is kept.
    this.router.navigate(['/patients', this.patientId()], {
      queryParams: { tab: tab.toLowerCase() },
    });
  }

  onAlertClick(alert: AlertItem): void {
    const ref = this.dialog.open(AlertActionDialogComponent, {
      width: '520px',
      data: alert.dialog,
      ariaLabelledBy: 'alert-modal-title',
    });

    ref.afterClosed().subscribe((result) => {
      if (result?.confirmed) {
        this.resolvePharmacistAlert(alert.id);
      }
    });
  }

  private resolvePharmacistAlert(alertId: string): void {
    this.medicationApi
      .resolveAlert(alertId, { resolution_type: 'REVIEWED_ACCEPTABLE' })
      .subscribe({
        next: () => {
          this.pharmacistAlerts.update((items) =>
            items.map((a) =>
              a.id === alertId ? { ...a, status: 'RESOLVED' as const } : a
            )
          );
          this.toast.success('Alert resolved');
        },
        error: (err: Error) => {
          this.toast.error(`Failed to resolve alert: ${err.message}`);
        },
      });
  }

  readonly carePlanSections: CarePlanSection[] = [
    {
      title: 'Follow-up',
      items: [
        'Primary care visit within 7 days',
        'Cardiology follow-up within 14 days',
        'INR recheck within 48 hours',
      ],
    },
    {
      title: 'Medications',
      items: [
        'Continue Warfarin 5mg QD with monitoring',
        'Continue Aspirin 81mg QD unless instructed otherwise',
        'Resume Metformin 500mg BD with meals',
      ],
    },
    {
      title: 'Warning Signs',
      items: [
        'Bleeding, bruising, or black stools',
        'Shortness of breath or chest pain',
        'Rapid weight gain or swelling',
      ],
    },
    {
      title: 'Patient Education',
      items: [
        'Low sodium diet for CHF management',
        'Daily weight logging',
        'When to call the care team',
      ],
    },
  ];

  onViewCarePlan(): void {
    this.dialog.open(CarePlanDialogComponent, {
      width: '560px',
      data: {
        patientName: this.patient().name,
        sections: this.carePlanSections,
      },
      ariaLabelledBy: 'care-plan-title',
    });
  }

  onReviewApproval(doc: BackendDocument): void {
    const generatedAt = doc.created_at
      ? new Date(doc.created_at).toLocaleString()
      : '—';
    const mode = this.isDocumentReviewable(doc) ? 'review' : 'view';
    const ref = this.dialog.open(DocumentApprovalDialogComponent, {
      width: '720px',
      maxHeight: '90vh',
      data: {
        doc,
        title: `${this.documentDisplayTitle(doc)} — ${this.documentStatusLabel(doc.status)}`,
        meta: `Generated ${generatedAt} · ${doc.generation_type ?? 'AI'}`,
        mode,
      },
      ariaLabelledBy: 'doc-approval-title',
    });

    ref.afterClosed().subscribe((result) => {
      if (result?.action === 'approve') {
        this.approveDocument(doc);
      } else if (result?.action === 'reject') {
        this.rejectDocument(doc, result.rejection_reason ?? '');
      }
    });
  }

  private approveDocument(doc: BackendDocument): void {
    this.documentService.approveDocument(doc.id, { notes: 'Approved via patient detail review.' }).subscribe({
      next: () => {
        this.documents.update((items) =>
          items.map((d) =>
            d.id === doc.id
              ? { ...d, status: 'APPROVED' as const, approved_at: new Date().toISOString() }
              : d
          )
        );
        this.toast.success(`${this.documentDisplayTitle(doc)} approved`);
      },
      error: (err: Error) => {
        this.toast.error(`Failed to approve document: ${err.message}`);
      },
    });
  }

  private rejectDocument(doc: BackendDocument, rejectionReason: string): void {
    if (!rejectionReason || rejectionReason.length < 10) {
      this.toast.error('Rejection reason must be at least 10 characters');
      return;
    }
    this.documentService.rejectDocument(doc.id, { rejection_reason: rejectionReason }).subscribe({
      next: () => {
        this.documents.update((items) =>
          items.map((d) =>
            d.id === doc.id
              ? { ...d, status: 'REJECTED' as const }
              : d
          )
        );
        this.toast.success(`${this.documentDisplayTitle(doc)} rejected`);
      },
      error: (err: Error) => {
        this.toast.error(`Failed to reject document: ${err.message}`);
      },
    });
  }

  regenerateDocument(doc: BackendDocument, event: MouseEvent): void {
    event.stopPropagation();
    const encounterId = this.patientId();
    if (!encounterId) {
      return;
    }

    if (this.isDocumentApproved(doc)) {
      this.toast.error('Approved documents cannot be regenerated');
      return;
    }

    const agentRole = this.agentRoleForDocumentType(doc.document_type);
    if (!agentRole) {
      this.toast.error(`Cannot regenerate ${this.documentDisplayTitle(doc)}`);
      return;
    }

    this.isGeneratingDocument.set(true);
    this.documentGenerationError.set(null);
    this.documentApi.generateDocument(encounterId, agentRole, true).subscribe({
      next: (newDoc) => {
        this.documents.update((items) => [newDoc, ...items]);
        this.isGeneratingDocument.set(false);
        this.toast.success(`Regenerated ${this.documentDisplayTitle(doc)}`);
      },
      error: (err: Error) => {
        this.documentGenerationError.set(err.message ?? 'Failed to regenerate document');
        this.isGeneratingDocument.set(false);
        this.toast.error(err.message ?? 'Failed to regenerate document');
      },
    });
  }

  private agentRoleForDocumentType(documentType: string): string | null {
    const map: Record<string, string> = {
      discharge_summary: 'documentation',
      medication_reconciliation: 'medication_reconciliation',
      follow_up_plan: 'follow_up_care',
      patient_instructions: 'patient_communication',
      transfer_summary: 'bed_management',
      care_transition_summary: 'coordinator',
    };
    return map[documentType] ?? null;
  }

  getMrnDisplay(): string {
    return this.mrnRevealed() ? this.patient().mrn : '●●●●●●';
  }

  toggleMrn(): void {
    this.mrnRevealed.update((v) => !v);
  }

  getRiskClass(level: string | undefined | null): string {
    return (level ?? 'low').toLowerCase();
  }

  getRiskBarWidth(score: number): string {
    return `${Math.round(score * 100)}%`;
  }

  getStatusDotClass(status: string): string {
    switch (status) {
      case 'ok': return 'ok';
      case 'warn': return 'warn';
      case 'pending': return 'pending';
      default: return 'pending';
    }
  }

  getAgentStatusColor(status: string): string {
    switch (status) {
      case 'ok': return '#16a34a';
      case 'warn': return '#d97706';
      case 'pending': return '#6b7280';
      default: return '#6b7280';
    }
  }

  getTaskPriorityClass(priority: string): string {
    switch (priority) {
      case 'HIGH': return 'priority-high';
      case 'MEDIUM': return 'priority-medium';
      case 'LOW': return 'priority-low';
      default: return 'priority-low';
    }
  }

  getTimelineDotClass(type: string): string {
    return type;
  }

  retryLoad(): void {
    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (patientId) {
      this.loadPatient(patientId);
      this.loadAgentTasks(patientId);
      this.loadDocuments(patientId);
      this.loadMedications(patientId);
      this.loadPharmacistAlerts(patientId);
      this.loadTimeline(patientId);
    }
  }

  refreshAll(): void {
    const patientId = this.patientId();
    if (!patientId) {
      return;
    }
    this.loadPatient(patientId);
    this.loadAgentTasks(patientId);
    this.loadDocuments(patientId);
    this.loadMedications(patientId);
    this.loadPharmacistAlerts(patientId);
    this.loadTimeline(patientId);
  }

  refreshAgentTasks(): void {
    const patientId = this.patientId();
    if (patientId) {
      this.loadAgentTasks(patientId);
    }
  }

  refreshDocuments(): void {
    const patientId = this.patientId();
    if (patientId) {
      this.loadDocuments(patientId);
    }
  }

  generateDocument(): void {
    const encounterId = this.patientId();
    const agentRole = this.selectedAgentRole();
    if (!encounterId) {
      return;
    }
    this.isGeneratingDocument.set(true);
    this.documentGenerationError.set(null);
    this.documentApi.generateDocument(encounterId, agentRole).subscribe({
      next: (doc) => {
        this.documents.update((items) => [doc, ...items]);
        this.isGeneratingDocument.set(false);
        const label = this.agentRoleOptions.find((o) => o.value === agentRole)?.documentType ?? agentRole;
        this.toast.success(`Generated ${label}`);
      },
      error: (err: Error) => {
        this.documentGenerationError.set(err.message ?? 'Failed to generate document');
        this.isGeneratingDocument.set(false);
        this.toast.error(err.message ?? 'Failed to generate document');
      },
    });
  }

  refreshMedications(): void {
    const patientId = this.patientId();
    if (patientId) {
      this.loadMedications(patientId);
    }
  }

  refreshAlerts(): void {
    const patientId = this.patientId();
    if (patientId) {
      this.loadPharmacistAlerts(patientId);
    }
  }

  refreshTimeline(): void {
    const patientId = this.patientId();
    if (patientId) {
      this.loadTimeline(patientId);
    }
  }

  goBack(): void {
    this.router.navigate(['/patients']);
  }

  // Encounter registration
}
