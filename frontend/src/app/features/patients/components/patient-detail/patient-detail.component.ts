import { Component, signal, inject, computed, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
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
import { PatientApiService } from '../../services/patient-api.service';
import { PatientDetail } from '../../models/patient.model';

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

interface AgentTask {
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
  imports: [CommonModule, RouterModule, MatIconModule, MatDialogModule],
  templateUrl: './patient-detail.component.html',
  styleUrl: './patient-detail.component.scss',
})
export class PatientDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);
  private readonly toast = inject(ToastService);
  private readonly patientApi = inject(PatientApiService);

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

  readonly agentTasks = computed<AgentTask[]>(() => {
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
  });

  readonly pendingApprovals = signal<DocumentApprovalDialogData[]>([
    { title: 'Discharge Summary — Draft', meta: 'Generated 14:32 · Documentation Agent · 30 seconds', aiAssisted: true },
  ]);

  readonly pendingApprovalCount = computed(() => this.pendingApprovals().length);

  readonly alerts = signal<AlertItem[]>([
    {
      id: 'alert-interaction',
      type: 'critical',
      title: 'Major Drug Interaction',
      text: 'Warfarin + Aspirin — increased bleeding risk. Review before discharge.',
      link: 'Resolve →',
      dialog: {
        title: 'Resolve Drug Interaction: Warfarin + Aspirin',
        severity: 'Major',
        risk: 'Increased bleeding — pharmacodynamic synergy',
        description:
          'Warfarin + Aspirin increases bleeding risk. Confirm management plan before discharge.',
        checklist: [
          'Monitor INR within 48 hours of discharge',
          'Consider dose adjustment per prescriber',
          'Patient education on bleeding precautions',
        ],
        confirmLabel: 'Mark Resolved',
      },
    },
    {
      id: 'alert-missing',
      type: 'warning',
      title: 'Chronic Medication Missing',
      text: 'Metformin 500mg BD not on discharge Rx. Patient has Type 2 Diabetes.',
      link: 'Review →',
      dialog: {
        title: 'Review Chronic Medication Missing: Metformin',
        description:
          'Metformin 500mg BD is not on the Discharge Rx. Patient has Type 2 Diabetes (ICD-10: E11.9).',
        checklist: [
          'Confirm intentional omission with prescriber',
          'Add Metformin to Discharge Rx if continuing',
          'Document reason in reconciliation notes',
        ],
        confirmLabel: 'Flag for Review',
      },
    },
  ]);

  readonly activeAlertCount = computed(() => this.alerts().length);

  readonly riskFactors = signal<RiskFactor[]>([
    { text: 'History of CHF readmission within 30 days' },
    { text: 'No primary care follow-up scheduled' },
    { text: 'Complex medication regimen (8+ meds)' },
    { text: 'Social determinants: transportation barrier' },
  ]);

  readonly documents = signal<{ title: string; status: string; aiAssisted: boolean }[]>([
    { title: 'Discharge Summary', status: 'Pending Review', aiAssisted: true },
    { title: 'After-Visit Instructions', status: 'Approved', aiAssisted: true },
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

  setTab(tab: string): void {
    this.activeTab.set(tab);

    // Per wireframe SCR-004, Medications navigates to SCR-005 and Documents
    // navigates to SCR-006. Overview, Tasks, and Timeline remain in-place.
    if (tab === 'Medications') {
      this.router.navigate(['/patients', this.patientId(), 'medications']);
    } else if (tab === 'Documents') {
      this.router.navigate(['/patients', this.patientId(), 'documents']);
    } else if (tab === 'Overview') {
      this.router.navigate(['/patients', this.patientId()]);
    } else {
      this.router.navigate(['/patients', this.patientId()], {
        queryParams: { tab: tab.toLowerCase() },
      });
    }
  }

  onAlertClick(alert: AlertItem): void {
    const ref = this.dialog.open(AlertActionDialogComponent, {
      width: '520px',
      data: alert.dialog,
      ariaLabelledBy: 'alert-modal-title',
    });

    ref.afterClosed().subscribe((result) => {
      if (result?.confirmed) {
        this.alerts.update((items) => items.filter((a) => a.id !== alert.id));
        this.toast.success(`${alert.title} ${alert.link.replace(' →', '')}`);
      }
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

  onReviewApproval(approval: DocumentApprovalDialogData): void {
    const ref = this.dialog.open(DocumentApprovalDialogComponent, {
      width: '640px',
      data: approval,
      ariaLabelledBy: 'doc-approval-title',
    });

    ref.afterClosed().subscribe((result) => {
      if (result?.action === 'approve') {
        this.pendingApprovals.update((items) =>
          items.filter((a) => a.title !== approval.title),
        );
        this.toast.success(`${approval.title} approved`);
      } else if (result?.action === 'reject') {
        this.toast.error(`${approval.title} rejected`);
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
    }
  }

  goBack(): void {
    this.router.navigate(['/patients']);
  }
}
