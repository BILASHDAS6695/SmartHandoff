import {
  Component, OnInit, Input, ChangeDetectionStrategy, signal, inject
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatDialog } from '@angular/material/dialog';
import { MedicationApiService } from '../../services/medication-api.service';
import { MedicationReconciliation, MedicationRow } from '../../models/medication-row.model';
import { RiskBadgeComponent } from '../../../../shared/components/risk-badge/risk-badge.component';

/**
 * Three-panel medication reconciliation table for the pharmacist role.
 * Displays Pre-Admit / Inpatient / Discharge columns side-by-side.
 * Reuses <app-risk-badge> with severity input for interaction badges.
 *
 * Route: /patients/:patientId/medications
 */
@Component({
  selector: 'app-medication-review',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatButtonModule,
    MatIconModule,
    RiskBadgeComponent,
  ],
  templateUrl: './medication-review.component.html',
  styleUrls: ['./medication-review.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MedicationReviewComponent implements OnInit {
  @Input({ required: true }) patientId!: string;

  private readonly medicationApi = inject(MedicationApiService);
  private readonly matDialog = inject(MatDialog);

  readonly displayedColumns = ['drugName', 'dose', 'frequency', 'severity'];

  reconciliation = signal<MedicationReconciliation | null>(null);
  isLoading = signal(true);
  hasError = signal(false);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading.set(true);
    this.hasError.set(false);
    this.medicationApi.getReconciliation(this.patientId).subscribe({
      next: (data) => {
        this.reconciliation.set(data);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  /** Opens AlertResolutionModalComponent when a severity badge is clicked */
  onBadgeClick(row: MedicationRow): void {
    if (row.alertId) {
      import('../alert-resolution-modal/alert-resolution-modal.component').then(({ AlertResolutionModalComponent }) => {
        this.matDialog
          .open(AlertResolutionModalComponent, {
            width: '600px',
            data: { alertId: row.alertId },
          })
          .afterClosed()
          .subscribe((resolved) => {
            if (resolved) {
              // Refresh medication data to clear badge and update UI
              this.load();
            }
          });
      });
    }
  }
}
