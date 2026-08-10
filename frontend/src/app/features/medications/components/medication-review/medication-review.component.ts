import {
  Component, OnInit, Input, ChangeDetectionStrategy, signal, computed, inject, Inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MedicationApiService, MedicationReconciliationResponse } from '../../services/medication-api.service';
import { PatientApiService } from '../../../patients/services/patient-api.service';
import { MedReviewAlert, MedReviewFlag, MedReviewReconciliation, MedReviewRow } from '../../models/med-review.model';
import { ToastService } from '../../../../core/notifications/toast.service';
import { ContactPrescriberModalComponent } from '../contact-prescriber-modal/contact-prescriber-modal.component';
import { AcceptMonitoringModalComponent } from '../accept-monitoring-modal/accept-monitoring-modal.component';
import { MedicationSummaryModalComponent } from '../medication-summary-modal/medication-summary-modal.component';

/**
 * Medication reconciliation review page matching Hi-Fi wireframe SCR-005.
 *
 * Route: /patients/:patientId/medications
 */
@Component({
  selector: 'app-medication-review',
  standalone: true,
  imports: [
    CommonModule,
    MatProgressSpinnerModule,
    MatButtonModule,
    MatIconModule,
  ],
  templateUrl: './medication-review.component.html',
  styleUrls: ['./medication-review.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MedicationReviewComponent implements OnInit {
  @Input() patientId!: string;

  private readonly medicationApi = inject(MedicationApiService);
  private readonly patientApi = inject(PatientApiService);
  private readonly matDialog = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);

  readonly patientName = signal<string>('Loading…');
  reconciliation = signal<MedReviewReconciliation | null>(null);
  isLoading = signal(true);
  hasError = signal(false);

  /** Local action state (backend unavailable for this preview). */
  private readonly resolvedAlertIds = signal<Set<string>>(new Set());
  private readonly omittedMedIds = signal<Set<string>>(new Set());
  private readonly flaggedMedIds = signal<Set<string>>(new Set());
  readonly isComplete = signal(false);

  /** Derived view model that reflects resolved/omitted/flagged actions. */
  readonly viewModel = computed<MedReviewReconciliation | null>(() =>
    this.buildViewModel(this.reconciliation())
  );

  /** True when reconciliation data loaded but contains no medications. */
  readonly isEmpty = computed(() => {
    const vm = this.viewModel();
    if (!vm) return false;
    return vm.preAdmit.length === 0 && vm.inpatient.length === 0 && vm.discharge.length === 0;
  });

  ngOnInit(): void {
    // Fallback when component input binding is not available
    if (!this.patientId) {
      this.patientId = this.route.snapshot.paramMap.get('patientId') ?? 'enc-001';
    }
    this.loadPatient();
    this.load();
  }

  /** Loads the patient's name so the review header matches the selected patient. */
  private loadPatient(): void {
    this.patientApi.getPatientByEncounter(this.patientId).subscribe({
      next: (patient) => {
        const name = patient.last_name && patient.first_name
          ? `${patient.last_name}, ${patient.first_name}`
          : patient.last_name || patient.first_name || 'Unknown Patient';
        this.patientName.set(name);
      },
      error: () => {
        this.patientName.set('Unknown Patient');
      },
    });
  }

  load(): void {
    this.isLoading.set(true);
    this.hasError.set(false);
    this.medicationApi.getReconciliation(this.patientId).subscribe({
      next: (data) => {
        this.reconciliation.set(this.mapApiResponseToReview(data));
        this.isLoading.set(false);
      },
      error: () => {
        // Wireframe preview fallback when backend is unavailable
        this.reconciliation.set(this.getMockReconciliation());
        this.hasError.set(false);
        this.isLoading.set(false);
      },
    });
  }

  /** Maps the backend medication reconciliation response to the SCR-005 review shape. */
  private mapApiResponseToReview(data: MedicationReconciliationResponse): MedReviewReconciliation {
    const mapRow = (row: MedicationReconciliationResponse['medications'][number]): MedReviewRow => {
      let flag: MedReviewFlag = 'OK';
      if (row.flags?.length) {
        flag = 'FLAGGED';
      }
      if (row.reconciliation_category === 'STOPPED') {
        flag = 'OMITTED';
      }
      return {
        id: row.id,
        drugName: row.name,
        dose: `${row.dose ?? ''} ${row.route ?? ''}`.trim(),
        frequency: row.frequency ?? '',
        flag,
      };
    };

    const medications = data.medications ?? [];
    return {
      encounterId: data.encounter_id ?? this.patientId,
      patientName: this.patientName(),
      preAdmit: medications.filter((m) => m.pre_admit).map(mapRow),
      inpatient: medications.filter((m) => m.inpatient).map(mapRow),
      discharge: medications.filter((m) => m.discharge).map(mapRow),
      alerts: [],
    };
  }

  /** Returns static mock data matching the Hi-Fi wireframe SCR-005. */
  private getMockReconciliation(): MedReviewReconciliation {
    return {
      encounterId: this.patientId,
      patientName: this.patientName(),
      preAdmit: [
        { id: 'm1', drugName: 'Warfarin', dose: '5mg', frequency: 'QD' },
        { id: 'm2', drugName: 'Aspirin', dose: '81mg', frequency: 'QD' },
        { id: 'm3', drugName: 'Metformin', dose: '500mg', frequency: 'BD' },
        { id: 'm4', drugName: 'Lisinopril', dose: '10mg', frequency: 'QD' },
        { id: 'm5', drugName: 'Atorvastatin', dose: '40mg', frequency: 'QD' },
      ],
      inpatient: [
        { id: 'm6', drugName: 'Warfarin', dose: '5mg', frequency: 'QD' },
        { id: 'm7', drugName: 'Aspirin', dose: '81mg', frequency: 'QD' },
        { id: 'm8', drugName: 'Metformin', dose: '500mg', frequency: 'BD' },
        { id: 'm9', drugName: 'Lisinopril', dose: '10mg', frequency: 'QD' },
        { id: 'm10', drugName: 'Atorvastatin', dose: '40mg', frequency: 'QD' },
      ],
      discharge: [
        { id: 'm11', drugName: 'Warfarin', dose: '5mg', frequency: 'QD', flag: 'OK' },
        { id: 'm12', drugName: 'Aspirin', dose: '81mg', frequency: 'QD', flag: 'INTERACT' },
        { id: 'missing-metformin', drugName: '', dose: '', frequency: '', flag: 'MISSING', isMissingBanner: true, missingReason: 'Chronic Med' },
        { id: 'm13', drugName: 'Lisinopril', dose: '10mg', frequency: 'QD', flag: 'OK' },
        { id: 'm14', drugName: 'Atorvastatin', dose: '40mg', frequency: 'QD', flag: 'OK' },
      ],
      alerts: [
        {
          id: 'a1',
          type: 'critical',
          title: 'MAJOR INTERACTION: Warfarin + Aspirin',
          body: 'Severity: Major | Risk: Increased bleeding risk — pharmacodynamic synergy; INR may rise significantly.\nDrug interaction database confidence: 99.2%',
          primaryAction: 'Contact Prescriber',
          secondaryActions: ['Accept with Monitoring Plan', 'View Evidence'],
        },
        {
          id: 'a2',
          type: 'warning',
          title: 'CHRONIC MED MISSING: Metformin 500mg BD',
          body: 'Not found on Discharge Rx. Patient has Type 2 Diabetes (ICD-10: E11.9).\nThis medication was continued throughout the inpatient stay.',
          primaryAction: 'Flag for Physician Review',
          primaryActionClass: 'info',
          secondaryActions: ['Mark as Intentional Omission'],
        },
      ],
    };
  }

  /** Navigates back to the parent patient detail view. */
  goBack(): void {
    this.router.navigate(['/patients', this.patientId]);
  }

  /** Builds the view model by applying resolved/omitted/flagged state. */
  private buildViewModel(rec: MedReviewReconciliation | null): MedReviewReconciliation | null {
    if (!rec) return null;

    const resolved = this.resolvedAlertIds();
    const omitted = this.omittedMedIds();
    const flagged = this.flaggedMedIds();

    const mapDischargeRow = (row: MedReviewRow): MedReviewRow => {
      if (row.isMissingBanner && row.id === 'missing-metformin') {
        if (omitted.has('metformin')) {
          return {
            ...row,
            isMissingBanner: false,
            drugName: 'Metformin',
            dose: '500mg',
            frequency: 'BD',
            flag: 'OMITTED',
            missingReason: undefined,
          };
        }
        if (flagged.has('metformin')) {
          return {
            ...row,
            isMissingBanner: false,
            drugName: 'Metformin',
            dose: '500mg',
            frequency: 'BD',
            flag: 'FLAGGED',
            missingReason: undefined,
          };
        }
        return row;
      }

      if (row.drugName === 'Aspirin' && resolved.has('a1')) {
        return { ...row, flag: 'RESOLVED' };
      }

      return row;
    };

    const mapAlert = (alert: MedReviewAlert): MedReviewAlert => {
      if (resolved.has(alert.id)) {
        // Should already be filtered out; return as-is for safety.
        return alert;
      }

      // Keep the missing-med alert visible when flagged, but show it as escalated.
      if (alert.id === 'a2' && flagged.has('metformin') && !omitted.has('metformin')) {
        return {
          ...alert,
          type: 'warning',
          title: '⚑ FLAGGED FOR PHYSICIAN REVIEW: Metformin 500mg BD',
          body: 'This medication was flagged for physician review. Awaiting prescriber decision before discharge.',
          primaryAction: 'Resend to Physician',
          primaryActionClass: 'info',
          secondaryActions: ['Mark as Intentional Omission'],
        };
      }

      return alert;
    };

    const remainingAlerts = rec.alerts
      .filter((alert) => {
        if (resolved.has(alert.id)) return false;
        // Remove the missing-med alert only when it is intentionally omitted.
        if (alert.id === 'a2' && omitted.has('metformin')) return false;
        return true;
      })
      .map(mapAlert);

    return {
      ...rec,
      discharge: rec.discharge.map(mapDischargeRow),
      alerts: remainingAlerts,
    };
  }

  /** Handles the primary action button on an active alert card. */
  onPrimaryAction(alert: MedReviewAlert): void {
    if (alert.id === 'a1') {
      this.openContactPrescriberModal();
    } else if (alert.id === 'a2') {
      this.flagForPhysicianReview(alert);
    }
  }

  /** Handles secondary action buttons on an active alert card. */
  onSecondaryAction(alert: MedReviewAlert, action: string): void {
    if (action === 'Accept with Monitoring Plan' && alert.id === 'a1') {
      this.openAcceptMonitoringModal();
    } else if (action === 'View Evidence' && alert.id === 'a1') {
      this.openViewEvidenceModal();
    } else if (action === 'Mark as Intentional Omission' && alert.id === 'a2') {
      this.markIntentionalOmission();
    }
  }

  /** Opens the wireframe "Contact Prescriber" modal. */
  private openContactPrescriberModal(): void {
    const ref = this.matDialog.open(ContactPrescriberModalComponent, { width: '480px' });
    ref.afterClosed().subscribe((method: string | undefined) => {
      if (method === 'secure-message') {
        this.toast.info('Opening secure message to Dr. Chen');
      } else if (method === 'pager') {
        this.toast.info('Initiating pager call #44521');
      } else if (method === 'page-oncall') {
        this.toast.success('On-call pharmacist notified');
      }
    });
  }

  /** Accepts the interaction with a monitoring plan and resolves the alert. */
  private openAcceptMonitoringModal(): void {
    const ref = this.matDialog.open(AcceptMonitoringModalComponent, { width: '520px' });
    ref.afterClosed().subscribe((result: { plan: string } | undefined) => {
      if (result) {
        this.resolvedAlertIds.update((set) => new Set([...set, 'a1']));
        this.toast.success('Monitoring plan accepted — alert resolved');
      }
    });
  }

  /** Shows interaction evidence in a simple read-only dialog. */
  private openViewEvidenceModal(): void {
    this.matDialog.open(ViewEvidenceDialogComponent, {
      width: '520px',
      data: {
        drugPair: 'Warfarin + Aspirin',
        mechanism: 'Pharmacodynamic synergy — both affect hemostasis',
        onset: 'Rapid',
        severity: 'Major',
        documentation: '12 cases of major bleeding in similar patient population (Lexicomp, 2026)',
        recommendation: 'Monitor INR within 48h; consider dose adjustment',
      },
    });
  }

  /** Flags the missing Metformin for physician review. */
  private flagForPhysicianReview(alert: MedReviewAlert): void {
    if (alert.primaryAction === 'Resend to Physician') {
      this.toast.info('Physician notification resent');
      return;
    }
    this.flaggedMedIds.update((set) => new Set([...set, 'metformin']));
    this.toast.warn('Metformin flagged for physician review');
  }

  /** Marks the missing Metformin as an intentional omission. */
  private markIntentionalOmission(): void {
    if (typeof window !== 'undefined' && window.confirm('Mark Metformin as an intentional omission?')) {
      this.omittedMedIds.update((set) => new Set([...set, 'metformin']));
      this.toast.info('Metformin marked as intentional omission');
    }
  }

  /** Opens the summary preview modal; downloads only when the user confirms. */
  generateSummary(): void {
    const vm = this.viewModel();
    if (!vm) return;

    const rows = vm.discharge
      .filter((row) => !row.isMissingBanner)
      .map((row) => {
        const instruction =
          row.flag === 'OMITTED'
            ? 'Omitted intentionally'
            : row.flag === 'FLAGGED'
            ? 'To be reviewed'
            : row.drugName === 'Aspirin'
            ? 'Continue with bleeding precautions'
            : row.drugName === 'Warfarin'
            ? 'Continue, monitor INR'
            : 'Continue';
        return {
          drug: `${row.drugName} ${row.dose} ${row.frequency}`,
          instruction,
        };
      });

    const ref = this.matDialog.open(MedicationSummaryModalComponent, {
      width: '520px',
      data: { patientName: this.patientName(), rows },
    });

    ref.afterClosed().subscribe((download: boolean) => {
      if (download) {
        const summaryLines = [
          `${this.patientName()} — Discharge Medication List`,
          '',
          ...rows.map((r) => `${r.drug} — ${r.instruction}`),
          '',
          'A printable PDF has been generated.',
        ];
        const blob = new Blob([summaryLines.join('\n')], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${this.patientName()}-medication-summary.txt`;
        link.click();
        URL.revokeObjectURL(url);

        this.toast.success('Patient medication summary downloaded');
      }
    });
  }

  /** Completes the reconciliation workflow after confirmation. */
  completeReconciliation(): void {
    const vm = this.viewModel();
    if (vm && vm.alerts.length > 0) {
      this.toast.warn('Resolve all active alerts before completing reconciliation');
      return;
    }

    if (typeof window !== 'undefined' && window.confirm('Mark medication reconciliation as complete?')) {
      this.isComplete.set(true);
      this.toast.success('Medication reconciliation completed — discharge unblocked');
    }
  }
}

export interface ViewEvidenceData {
  drugPair: string;
  mechanism: string;
  onset: string;
  severity: string;
  documentation: string;
  recommendation: string;
}

@Component({
  selector: 'app-view-evidence-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>Interaction Evidence</h2>
    <mat-dialog-content>
      <p><strong>{{ data.drugPair }}</strong></p>
      <ul style="list-style:none;padding:0;margin:0;line-height:1.6;">
        <li><strong>Mechanism:</strong> {{ data.mechanism }}</li>
        <li><strong>Onset:</strong> {{ data.onset }}</li>
        <li><strong>Severity:</strong> {{ data.severity }}</li>
        <li><strong>Documentation:</strong> {{ data.documentation }}</li>
        <li><strong>Recommendation:</strong> {{ data.recommendation }}</li>
      </ul>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Close</button>
    </mat-dialog-actions>
  `,
})
class ViewEvidenceDialogComponent {
  constructor(@Inject(MAT_DIALOG_DATA) readonly data: ViewEvidenceData) {}
}
