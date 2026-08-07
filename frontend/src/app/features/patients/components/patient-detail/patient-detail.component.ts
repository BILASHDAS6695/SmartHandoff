import { Component, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';

interface PatientDetail {
  name: string;
  mrn: string;
  mrnMasked: string;
  dob: string;
  age: number;
  unit: string;
  bed: string;
  admissionDate: string;
  attending: string;
  riskScore: number;
  riskLevel: 'HIGH' | 'MED' | 'LOW';
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

interface PatientTask {
  id: string;
  title: string;
  meta: string;
  owner: string;
  priority: 'high' | 'medium' | 'low';
  done: boolean;
}

interface TimelineEvent {
  time: string;
  title: string;
  desc: string;
  type: 'alert' | 'warning' | 'success' | 'system' | 'default';
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
export class PatientDetailComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly activeTab = signal<string>('Overview');
  readonly tabs = signal<string[]>(['Overview', 'Medications', 'Documents', 'Tasks', 'Timeline']);

  readonly mrnRevealed = signal<boolean>(false);

  readonly patient = signal<PatientDetail>({
    name: 'Smith, John',
    mrn: '12345678',
    mrnMasked: '●●●●●●',
    dob: '1975-03-15',
    age: 51,
    unit: '4-West',
    bed: '4W-12',
    admissionDate: '2026-07-10',
    attending: 'Dr. Chen',
    riskScore: 0.82,
    riskLevel: 'HIGH',
  });

  readonly agentTasks = signal<AgentTask[]>([
    { name: 'Transition Coordinator', status: 'ok', label: 'Complete' },
    { name: 'Documentation Agent', status: 'ok', label: 'Draft ready' },
    { name: 'Medication Reconciliation', status: 'warn', label: '⚠ 2 alerts' },
    { name: 'Bed Management', status: 'ok', label: 'Assigned' },
    { name: 'Follow-up Care', status: 'pending', label: '● Pending' },
    { name: 'Patient Communications', status: 'ok', label: 'Active' },
  ]);

  readonly pendingApprovals = signal<{ title: string; meta: string }[]>([
    { title: 'Discharge Summary — Draft', meta: 'Generated 14:32 · Documentation Agent · 30 seconds' },
  ]);

  readonly alerts = signal<AlertItem[]>([
    {
      type: 'critical',
      title: 'Major Drug Interaction',
      text: 'Warfarin + Aspirin — increased bleeding risk. Review before discharge.',
      link: 'Resolve →',
    },
    {
      type: 'warning',
      title: 'Chronic Medication Missing',
      text: 'Metformin 500mg BD not on discharge Rx. Patient has Type 2 Diabetes.',
      link: 'Review →',
    },
  ]);

  readonly riskFactors = signal<RiskFactor[]>([
    { text: 'History of CHF readmission within 30 days' },
    { text: 'No primary care follow-up scheduled' },
    { text: 'Complex medication regimen (8+ meds)' },
    { text: 'Social determinants: transportation barrier' },
  ]);

  readonly openTasks = signal<PatientTask[]>([
    { id: 't1', title: 'Confirm follow-up appointment', meta: 'Due today · Follow-up Care', owner: 'CM', priority: 'high', done: false },
    { id: 't2', title: 'Review discharge summary draft', meta: 'Due today · Documentation', owner: 'MD', priority: 'high', done: false },
    { id: 't3', title: 'Arrange transport home', meta: 'Due tomorrow · Social Work', owner: 'SW', priority: 'medium', done: false },
  ]);

  readonly completedTasks = signal<PatientTask[]>([
    { id: 't4', title: 'Admission medication reconciliation', meta: 'Completed 07-10 · Pharmacy', owner: 'RX', priority: 'low', done: true },
    { id: 't5', title: 'Bed assignment', meta: 'Completed 07-10 · Bed Management', owner: 'BM', priority: 'low', done: true },
  ]);

  readonly timelineEvents = signal<TimelineEvent[]>([
    { time: 'Today 14:32', title: 'Discharge Summary Draft Generated', desc: 'Documentation Agent · 30 seconds', type: 'default' },
    { time: 'Today 11:15', title: 'Medication Reconciliation Alert', desc: 'Major interaction flagged: Warfarin + Aspirin', type: 'alert' },
    { time: 'Today 09:40', title: 'Follow-up Care Task Created', desc: 'Primary care appointment pending', type: 'warning' },
    { time: '2026-07-10 08:20', title: 'Patient Admitted', desc: 'Unit 4-West · Bed 4W-12', type: 'success' },
    { time: '2026-07-09 16:00', title: 'Transfer Order Placed', desc: 'From ED to 4-West', type: 'system' },
  ]);

  readonly documents = signal<{ title: string; status: string; aiAssisted: boolean }[]>([
    { title: 'Discharge Summary', status: 'Pending Review', aiAssisted: true },
    { title: 'After-Visit Instructions', status: 'Approved', aiAssisted: true },
  ]);

  constructor() {
    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (patientId) {
      // Static preview — no API call
    }

    // Sync active tab with the current route when landing on a child route.
    const urlSegments = this.route.snapshot.url.map((s) => s.path);
    const lastSegment = urlSegments[urlSegments.length - 1];
    if (lastSegment === 'medications') {
      this.activeTab.set('Medications');
    } else if (lastSegment === 'documents') {
      this.activeTab.set('Documents');
    }
  }

  setTab(tab: string): void {
    this.activeTab.set(tab);

    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (!patientId) {
      return;
    }

    if (tab === 'Medications') {
      this.router.navigate(['/patients', patientId, 'medications']);
    } else if (tab === 'Documents') {
      this.router.navigate(['/patients', patientId, 'documents']);
    }
    // Overview, Tasks, and Timeline are rendered in-place by this component.
  }

  toggleMrn(): void {
    this.mrnRevealed.update((v) => !v);
  }

  getMrnDisplay(): string {
    return this.mrnRevealed() ? this.patient().mrn : this.patient().mrnMasked;
  }

  getRiskClass(level: string): string {
    return level.toLowerCase();
  }

  getRiskBarWidth(score: number): number {
    return Math.round(score * 100);
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
    return priority;
  }

  getTimelineDotClass(type: string): string {
    switch (type) {
      case 'alert': return 'alert';
      case 'warning': return 'warning';
      case 'success': return 'success';
      case 'system': return 'system';
      default: return 'default';
    }
  }

  goBack(): void {
    this.router.navigate(['/patients']);
  }
}
