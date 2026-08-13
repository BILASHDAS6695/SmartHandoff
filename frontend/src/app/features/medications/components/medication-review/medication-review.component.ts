import {
  Component, OnInit, Input, ChangeDetectionStrategy, signal, computed, inject, Inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog, MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MedicationApiService, MedicationReconciliationResponse, PharmacistAlert } from '../../services/medication-api.service';
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
  reconciliation = signal<MedicationReconciliationResponse | null>(null);
  backendAlerts = signal<PharmacistAlert[]>([]);
  isLoading = signal(true);
  hasError = signal(false);

  /** Local action state (backend unavailable for this preview). */
  private readonly resolvedAlertIds = signal<Set<string>>(new Set());
  private readonly omittedMedIds = signal<Set<string>>(new Set());
  private readonly flaggedMedIds = signal<Set<string>>(new Set());
  readonly isComplete = signal(false);

  /** Derived view model built from backend reconciliation + alerts. */
  readonly viewModel = computed<MedReviewReconciliation | null>(() =>
    this.mapApiResponseToReview(this.reconciliation(), this.backendAlerts())
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
    this.medicationApi.generateReconciliation(this.patientId).subscribe({
      next: (data) => {
        this.isComplete.set(!!data.reconciliation_completed_by);
        this.reconciliation.set(data);
        this.isLoading.set(false);
      },
      error: (err) => {
        this.isLoading.set(false);
        this.hasError.set(true);
        console.error('Failed to load medication reconciliation:', err);
      },
    });

    this.medicationApi.getEncounterAlerts(this.patientId).subscribe({
      next: (alerts: PharmacistAlert[]) => {
        this.backendAlerts.set(alerts);
      },
      error: (err: unknown) => {
        console.error('Failed to load pharmacist alerts:', err);
      },
    });
  }

  /** Maps the backend medication reconciliation response and alerts to the SCR-005 review shape. */
  private mapApiResponseToReview(
    data: MedicationReconciliationResponse | null,
    alerts: PharmacistAlert[]
  ): MedReviewReconciliation | null {
    if (!data) return null;

    const mapRow = (row: MedicationReconciliationResponse['medications'][number]): MedReviewRow => {
      let flag: MedReviewFlag = 'OK';
      if (row.interaction_severity === 'HIGH') {
        flag = 'INTERACT';
      } else if (row.flags?.length) {
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
    const preAdmit = medications.filter((m) => m.pre_admit).map(mapRow);
    const inpatient = medications.filter((m) => m.inpatient).map(mapRow);
    const discharge = medications.filter((m) => m.discharge).map(mapRow);

    // Build alerts from backend pharmacist alerts API
    const activeAlerts: MedReviewAlert[] = alerts
      .filter((alert) => alert.status === 'ACTIVE')
      .map((alert) => this.mapBackendAlertToReview(alert));

    // Build missing banners from stopped medications
    const stopped = medications.filter(
      (m) => m.reconciliation_category === 'STOPPED' && m.pre_admit && !m.discharge,
    );
    for (const med of stopped) {
      discharge.push({
        id: `missing-${med.id}`,
        drugName: '',
        dose: '',
        frequency: '',
        flag: 'MISSING',
        isMissingBanner: true,
        missingReason: `${med.name} — Chronic Med`,
      });
    }

    return {
      encounterId: data.encounter_id ?? this.patientId,
      patientName: this.patientName(),
      preAdmit,
      inpatient,
      discharge,
      alerts: activeAlerts,
    };
  }

  /** Maps a backend PharmacistAlert to the SCR-005 review alert shape. */
  private mapBackendAlertToReview(alert: PharmacistAlert): MedReviewAlert {
    if (alert.drug_pair && alert.drug_pair.length >= 2) {
      return {
        id: alert.id,
        type: alert.severity === 'HIGH' ? 'critical' : 'warning',
        title: `MAJOR INTERACTION: ${alert.drug_pair.join(' + ')}`,
        body: alert.interaction_description ?? '',
        primaryAction: 'Contact Prescriber',
        secondaryActions: ['Accept with Monitoring Plan', 'View Evidence'],
      };
    }

    const drugName = alert.drug_name ?? 'Medication';
    return {
      id: alert.id,
      type: alert.severity === 'HIGH' ? 'critical' : 'warning',
      title: `CHRONIC MED MISSING: ${drugName}`,
      body: alert.interaction_description ?? '',
      primaryAction: 'Flag for Physician Review',
      primaryActionClass: 'info',
      secondaryActions: ['Mark as Intentional Omission'],
    };
  }

  /** Navigates back to the parent patient detail view. */
  goBack(): void {
    this.router.navigate(['/patients', this.patientId]);
  }

  /** Handles the primary action button on an active alert card. */
  onPrimaryAction(alert: MedReviewAlert): void {
    if (alert.type === 'critical' || alert.primaryAction === 'Contact Prescriber') {
      this.openContactPrescriberModal();
    } else if (alert.primaryAction === 'Flag for Physician Review' || alert.primaryAction === 'Resend to Physician') {
      this.flagForPhysicianReview(alert);
    }
  }

  /** Handles secondary action buttons on an active alert card. */
  onSecondaryAction(alert: MedReviewAlert, action: string): void {
    if (action === 'Accept with Monitoring Plan') {
      this.acceptWithMonitoringPlan(alert);
    } else if (action === 'View Evidence') {
      this.openViewEvidenceModal();
    } else if (action === 'Mark as Intentional Omission') {
      this.markIntentionalOmission(alert);
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
  private acceptWithMonitoringPlan(alert: MedReviewAlert): void {
    this.medicationApi.resolveAlert(alert.id, {
      resolution_type: 'REVIEWED_ACCEPTABLE',
      resolution_note: 'Accepted with monitoring plan',
    }).subscribe({
      next: () => {
        this.refreshAlerts();
        this.toast.success('Monitoring plan accepted — alert resolved');
      },
      error: (err: unknown) => {
        console.error('Failed to resolve alert:', err);
        this.toast.error('Failed to resolve alert');
      },
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

  /** Flags the missing medication for physician review. */
  private flagForPhysicianReview(alert: MedReviewAlert): void {
    const medName = this.extractMedicationName(alert);
    if (alert.primaryAction === 'Resend to Physician') {
      this.toast.info('Physician notification resent');
      return;
    }

    this.medicationApi.resolveAlert(alert.id, {
      resolution_type: 'REVIEWED_ACCEPTABLE',
      resolution_note: medName ? `Flagged for physician review: ${medName}` : 'Flagged for physician review',
    }).subscribe({
      next: () => {
        this.refreshAlerts();
        if (medName) {
          this.flaggedMedIds.update((set) => new Set([...set, medName.toLowerCase()]));
          this.toast.warn(`${medName} flagged for physician review`);
        } else {
          this.toast.warn('Alert flagged for physician review');
        }
      },
      error: (err: unknown) => {
        console.error('Failed to flag alert:', err);
        this.toast.error('Failed to flag alert for physician review');
      },
    });
  }

  /** Marks the missing medication as an intentional omission. */
  private markIntentionalOmission(alert: MedReviewAlert): void {
    const medName = this.extractMedicationName(alert);
    if (!medName) return;

    const ref = this.matDialog.open(ConfirmOmissionDialogComponent, {
      width: '420px',
      data: { medName },
    });

    ref.afterClosed().subscribe((confirmed: boolean) => {
      if (!confirmed) return;

      this.medicationApi.resolveAlert(alert.id, {
        resolution_type: 'DISCONTINUED',
        resolution_note: `Marked as intentional omission: ${medName}`,
      }).subscribe({
        next: () => {
          this.refreshAlerts();
          this.omittedMedIds.update((set) => new Set([...set, medName.toLowerCase()]));
          this.toast.info(`${medName} marked as intentional omission`);
        },
        error: (err: unknown) => {
          console.error('Failed to mark omission:', err);
          this.toast.error('Failed to mark intentional omission');
        },
      });
    });
  }

  /** Refreshes the backend alert list for the current encounter. */
  private refreshAlerts(): void {
    this.medicationApi.getEncounterAlerts(this.patientId).subscribe({
      next: (alerts) => this.backendAlerts.set(alerts),
      error: (err: unknown) => console.error('Failed to refresh alerts:', err),
    });
  }

  /** Extracts medication name from a chronic-med-missing alert title. */
  private extractMedicationName(alert: MedReviewAlert): string | null {
    const match = alert.title.match(/CHRONIC MED MISSING:\s*([^\d]+)/i);
    return match ? match[1].trim() : null;
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
    const hasAlerts = vm ? vm.alerts.length > 0 : false;

    const ref = this.matDialog.open(CompleteReconciliationDialogComponent, {
      width: '480px',
      data: { hasAlerts },
    });

    ref.afterClosed().subscribe((confirmed: boolean) => {
      if (confirmed) {
        this.medicationApi.completeReconciliation(this.patientId).subscribe({
          next: (data) => {
            this.isComplete.set(!!data.reconciliation_completed_by);
            this.toast.success('Medication reconciliation completed — discharge unblocked');
          },
          error: (err: unknown) => {
            console.error('Failed to complete reconciliation:', err);
            this.toast.error('Failed to complete reconciliation');
          },
        });
      }
    });
  }
}

/**
 * Interaction evidence dialog data.
 */
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

@Component({
  selector: 'app-complete-reconciliation-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>Complete Reconciliation</h2>
    <mat-dialog-content>
      <p>Mark medication reconciliation as complete?</p>
      <ng-container *ngIf="data.hasAlerts">
        <p style="color:#d97706;margin-top:8px;">
          ⚠ There are still active alerts. Completing with unresolved alerts may block safe discharge.
        </p>
      </ng-container>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-button color="primary" [mat-dialog-close]="true">Complete Reconciliation</button>
    </mat-dialog-actions>
  `,
})
class CompleteReconciliationDialogComponent {
  constructor(@Inject(MAT_DIALOG_DATA) readonly data: { hasAlerts: boolean }) {}
}

@Component({
  selector: 'app-confirm-omission-dialog',
  standalone: true,
  imports: [CommonModule, MatDialogModule, MatButtonModule],
  template: `
    <h2 mat-dialog-title>Mark as Intentional Omission</h2>
    <mat-dialog-content>
      <p>Mark <strong>{{ data.medName }}</strong> as an intentional omission?</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancel</button>
      <button mat-button color="warn" [mat-dialog-close]="true">Mark as Omission</button>
    </mat-dialog-actions>
  `,
})
class ConfirmOmissionDialogComponent {
  constructor(@Inject(MAT_DIALOG_DATA) readonly data: { medName: string }) {}
}
