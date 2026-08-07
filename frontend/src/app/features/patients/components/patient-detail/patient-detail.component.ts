import { Component, signal, inject, OnInit, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';
import { PatientApiService } from '../../services/patient-api.service';
import { PatientDetail } from '../../models/patient.model';

interface PatientDetailViewModel {
  name: string;
  mrn: string;
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
  type: 'critical' | 'warning';
  title: string;
  text: string;
  link?: string;
}

interface AgentTask {
  name: string;
  status: 'ok' | 'warn' | 'pending';
  label: string;
}

interface RiskFactor {
  text: string;
}

interface ApprovalItem {
  title: string;
  meta: string;
}

interface PatientTask {
  id: string;
  title: string;
  meta: string;
  owner: string;
  priority: 'HIGH' | 'MEDIUM' | 'LOW';
  done: boolean;
}

interface TimelineEvent {
  type: 'admit' | 'transfer' | 'alert' | 'task' | 'note';
  time: string;
  title: string;
  desc: string;
}

/**
 * Patient Detail Component — matches Hi-Fi wireframe SCR-004.
 */
@Component({
  selector: 'app-patient-detail',
  standalone: true,
  imports: [CommonModule, RouterModule, MatIconModule],
  templateUrl: './patient-detail.component.html',
  styleUrl: './patient-detail.component.scss',
})
export class PatientDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly patientApi = inject(PatientApiService);

  readonly activeTab = signal<string>('Overview');
  readonly tabs = signal<string[]>(['Overview', 'Medications', 'Documents', 'Tasks', 'Timeline']);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);
  readonly mrnRevealed = signal<boolean>(false);

  readonly patient = signal<PatientDetailViewModel>({
    name: '',
    mrn: '●●●●●●',
    dob: '',
    age: 0,
    unit: '',
    room: '',
    bed: '—',
    admissionDate: '',
    attending: '—',
    riskScore: 0,
    riskLevel: 'LOW',
  });

  readonly alerts = signal<AlertItem[]>([
    {
      type: 'critical',
      title: 'High Readmission Risk',
      text: 'Risk score 0.82 — follow-up appointment not yet booked.',
      link: 'View Care Plan',
    },
    {
      type: 'warning',
      title: 'Medication Reconciliation Pending',
      text: 'Pharmacist review required before discharge.',
      link: 'Review Medications',
    },
  ]);

  readonly agentTasks = signal<AgentTask[]>([
    { name: 'Transition Coordinator', status: 'ok', label: 'Active' },
    { name: 'Documentation', status: 'ok', label: 'Active' },
    { name: 'Medication Reconciliation', status: 'warn', label: '2 alerts' },
    { name: 'Bed Management', status: 'ok', label: 'Active' },
    { name: 'Follow-up Care', status: 'pending', label: 'Pending' },
    { name: 'Patient Communications', status: 'ok', label: 'Active' },
  ]);

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

  readonly pendingApprovals = signal<ApprovalItem[]>([
    { title: 'Discharge Summary', meta: 'AI-generated • Pending physician approval' },
  ]);

  readonly patientTasks = signal<PatientTask[]>([
    { id: '1', title: 'Medication Reconciliation', meta: 'Pharmacist review required', owner: 'Pharmacy', priority: 'HIGH', done: false },
    { id: '2', title: 'Follow-up Appointment', meta: 'Schedule PCP visit within 7 days', owner: 'Transition', priority: 'HIGH', done: false },
    { id: '3', title: 'Transportation Arranged', meta: 'Confirmed for discharge day', owner: 'Case Mgmt', priority: 'MEDIUM', done: true },
  ]);

  readonly openTasks = computed(() => this.patientTasks().filter(t => !t.done));
  readonly completedTasks = computed(() => this.patientTasks().filter(t => t.done));

  readonly timelineEvents = signal<TimelineEvent[]>([
    { type: 'admit', time: '08:30 AM', title: 'Admitted to ICU', desc: 'Direct admit from ED' },
    { type: 'task', time: '10:15 AM', title: 'Medication Reconciliation Started', desc: 'Assigned to pharmacy' },
    { type: 'alert', time: '11:00 AM', title: 'High Readmission Risk Flagged', desc: 'Risk score 0.82' },
    { type: 'note', time: '02:45 PM', title: 'Physician Note Added', desc: 'Discharge planning initiated' },
  ]);

  ngOnInit(): void {
    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (patientId) {
      this.loadPatient(patientId);
    }
  }

  private loadPatient(encounterId: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.patientApi.getPatient(encounterId).subscribe({
      next: (detail: PatientDetail) => {
        this.patient.set({
          name: `${detail.last_name}, ${detail.first_name}`,
          mrn: detail.mrn_masked,
          dob: detail.date_of_birth,
          age: this.calculateAge(detail.date_of_birth),
          unit: detail.current_unit,
          room: detail.room_number,
          bed: detail.room_number ? `Bed ${detail.room_number}` : '—',
          admissionDate: detail.admission_date,
          attending: '—', // not yet stored in encounter schema
          riskScore: detail.risk_score ?? this.riskScoreFromTier(detail.risk_tier),
          riskLevel: detail.risk_tier,
        });
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.error.set(typeof err === 'object' && err !== null && 'message' in err ? String((err as { message: string }).message) : 'Failed to load patient details.');
        this.loading.set(false);
      },
    });
  }

  private calculateAge(dob: string): number {
    if (!dob) return 0;
    const birth = new Date(dob);
    const now = new Date();
    let age = now.getFullYear() - birth.getFullYear();
    const monthDiff = now.getMonth() - birth.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && now.getDate() < birth.getDate())) {
      age--;
    }
    return age;
  }

  private riskScoreFromTier(tier: string): number {
    switch (tier) {
      case 'HIGH': return 0.82;
      case 'MEDIUM': return 0.45;
      case 'LOW': return 0.18;
      default: return 0;
    }
  }

  setTab(tab: string): void {
    this.activeTab.set(tab);
    if (tab === 'Medications') {
      this.router.navigate(['medications'], { relativeTo: this.route });
    } else if (tab === 'Documents') {
      this.router.navigate(['documents'], { relativeTo: this.route });
    }
  }

  getMrnDisplay(): string {
    return this.mrnRevealed() ? this.patient().mrn : '●●●●●●';
  }

  toggleMrn(): void {
    this.mrnRevealed.update(v => !v);
  }

  getRiskClass(level: string): string {
    return level.toLowerCase();
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
