import { Component, signal, inject, computed, OnInit, OnDestroy } from '@angular/core';
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
import { AgentTaskResponse, AGENT_TYPE_DISPLAY_NAME, TaskStatus } from '@core/models';
import { PatientApiService } from '../../services/patient-api.service';
import { DocumentApiService, BackendDocument } from '@features/documents/services/document-api.service';
import {
  MedicationApiService,
  MedicationReconciliationResponse,
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
  private readonly medicationApi = inject(MedicationApiService);

  private taskUpdateSub?: Subscription;

  readonly activeTab = signal<string>('Overview');
  readonly tabs = signal<string[]>(['Overview', 'Medications', 'Documents', 'Tasks', 'Timeline']);
  readonly patientId = signal<string>('enc-001');

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

  readonly documents = signal<BackendDocument[]>([]);
  readonly isLoadingDocuments = signal<boolean>(false);
  readonly documentError = signal<string | null>(null);

  readonly medications = signal<MedicationReconciliationResponse | null>(null);
  readonly isLoadingMedications = signal<boolean>(false);
  readonly medicationError = signal<string | null>(null);

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

  readonly timelineEvents = signal<TimelineEvent[]>([
    { time: '08:00', title: 'Admission', desc: 'Patient admitted to 3N, room 312', type: 'admission' },
    { time: '09:30', title: 'Medication Reconciliation', desc: 'Home medications reviewed', type: 'medication' },
    { time: '14:32', title: 'Discharge Summary Draft', desc: 'AI-generated draft ready for review', type: 'document' },
    { time: '16:15', title: 'Alert Generated', desc: 'Major drug interaction flagged', type: 'alert' },
  ]);

  ngOnInit(): void {
    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (patientId) {
      this.patientId.set(patientId);
      this.loadPatient(patientId);
      this.loadAgentTasks(patientId);
      this.loadDocuments(patientId);
      this.loadMedications(patientId);
      this.loadPharmacistAlerts(patientId);
    }

    // Restore the tab requested by a returning child view (e.g. document review).
    const returnTab = this.route.snapshot.queryParamMap.get('tab');
    const matchedTab = this.tabs().find(
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
    this.medicationApi.getReconciliation(encounterId).subscribe({
      next: (data) => {
        this.medications.set(data);
        this.isLoadingMedications.set(false);
      },
      error: (err: Error) => {
        this.medicationError.set(err.message);
        this.isLoadingMedications.set(false);
      },
    });
  }

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
    switch (status) {
      case 'PENDING_REVIEW':
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
    const ref = this.dialog.open(DocumentApprovalDialogComponent, {
      width: '640px',
      data: {
        title: `${this.documentDisplayTitle(doc)} — Draft`,
        meta: `Generated ${generatedAt} · ${doc.generation_type ?? 'AI'}`,
        aiAssisted: doc.ai_assisted_label,
      },
      ariaLabelledBy: 'doc-approval-title',
    });

    ref.afterClosed().subscribe((result) => {
      if (result?.action === 'approve') {
        this.documents.update((items) =>
          items.map((d) =>
            d.id === doc.id
              ? { ...d, status: 'APPROVED' as const, approved_at: new Date().toISOString() }
              : d
          )
        );
        this.toast.success(`${this.documentDisplayTitle(doc)} approved`);
      } else if (result?.action === 'reject') {
        this.toast.error(`${this.documentDisplayTitle(doc)} rejected`);
      }
    });
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

  goBack(): void {
    this.router.navigate(['/patients']);
  }

  // Encounter registration
}
