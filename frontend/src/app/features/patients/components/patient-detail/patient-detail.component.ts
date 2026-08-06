import { Component, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MatIconModule } from '@angular/material/icon';

interface PatientDetail {
  name: string;
  mrn: string;
  dob: string;
  age: number;
  unit: string;
  room: string;
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
}

interface RiskFactor {
  text: string;
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

  readonly patient = signal<PatientDetail>({
    name: 'Smith, John',
    mrn: '●●●●●●',
    dob: '1975-03-15',
    age: 51,
    unit: '4-West',
    room: '412A',
    admissionDate: '2026-07-10',
    attending: 'Dr. David Chen',
    riskScore: 0.82,
    riskLevel: 'HIGH',
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
    { name: 'Transition Coordinator', status: 'ok' },
    { name: 'Documentation', status: 'ok' },
    { name: 'Medication Reconciliation', status: 'warn' },
    { name: 'Bed Management', status: 'ok' },
    { name: 'Follow-up Care', status: 'pending' },
    { name: 'Patient Communications', status: 'ok' },
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

  constructor() {
    const patientId = this.route.snapshot.paramMap.get('patientId');
    if (patientId) {
      // Static preview — no API call
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

  goBack(): void {
    this.router.navigate(['/patients']);
  }
}
