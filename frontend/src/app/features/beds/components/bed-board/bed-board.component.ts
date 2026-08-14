import { Component, OnInit, signal, inject, ChangeDetectionStrategy, OnDestroy, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatSelectModule } from '@angular/material/select';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog, MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { Subject, takeUntil } from 'rxjs';
import { BedDetailPanelComponent } from '../bed-detail-panel/bed-detail-panel.component';
import { BedDetailDto, BedDto, BedStatus, BedSuggestion, DischargePredictionDto, WaitingPatientForBed } from '../../models/bed.model';
import { BedBoardService } from '../../services/bed-board.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { AuthService } from '../../../../core/auth/auth.service';

/**
 * BedBoardComponent — Visual bed board floor plan matching Hi-Fi wireframe.
 */
@Component({
  selector: 'app-bed-board',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    BedDetailPanelComponent,
    MatProgressSpinnerModule,
    MatButtonToggleModule,
    MatSelectModule,
    MatIconModule,
    MatButtonModule,
    MatDialogModule,
  ],
  templateUrl: './bed-board.component.html',
  styleUrl: './bed-board.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedBoardComponent implements OnInit, OnDestroy {
  private readonly bedService = inject(BedBoardService);
  private readonly dialog = inject(MatDialog);
  private readonly signalR = inject(SignalRService);
  private readonly authService = inject(AuthService);
  private readonly destroy$ = new Subject<void>();

  // State signals
  readonly beds = signal<BedDto[]>([]);
  readonly suggestions = signal<BedSuggestion[]>([]);
  readonly suggestionsLoading = signal(false);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);
  readonly selectedBed = signal<BedDto | null>(null);
  readonly selectedBedDetail = signal<BedDetailDto | null>(null);
  readonly selectedBedDetailLoading = signal(false);
  readonly lastUpdated = signal<string>('14:39:01');

  readonly selectedUnit = signal<string>('All Units');
  readonly selectedStatus = signal<string>('All Status');

  readonly availableUnits = signal<string[]>(['All Units', '4-West', '3-North', 'ICU', 'CCU', 'MED', 'PEDS', 'SURG', 'General']);
  readonly availableStatuses = signal<string[]>(['All Status', 'Clean', 'Dirty', 'Occupied', 'Blocked']);

  readonly canManageSuggestions = computed(() => {
    const role = this.authService.currentUser()?.role?.toLowerCase();
    return role === 'bed_manager' || role === 'admin';
  });

  readonly dischargePredictionHours = signal<number>(4);
  readonly dischargePredictionOptions = signal<number[]>([1, 2, 4, 8, 12, 24]);
  readonly dischargePredictions = signal<DischargePredictionDto[]>([]);
  readonly dischargePredictionsLoading = signal(false);

  readonly filteredBeds = computed(() => {
    let result = this.beds();
    const unit = this.selectedUnit();
    const status = this.selectedStatus();

    if (unit !== 'All Units') {
      result = result.filter(b => b.unit === unit);
    }

    if (status !== 'All Status') {
      result = result.filter(b => this.mapStatusLabel(b.status) === status);
    }

    return result;
  });

  // Static mock data
  private readonly mockBeds: BedDto[] = [
    { bedId: '4W-01', unit: '4-West', status: 'OCCUPIED', patientName: 'Smith, J.', predictedDischargeTime: '16h', assignedNurse: null, riskTier: 'HIGH' },
    { bedId: '4W-02', unit: '4-West', status: 'DIRTY', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
    { bedId: '4W-03', unit: '4-West', status: 'VACANT', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
    { bedId: '4W-04', unit: '4-West', status: 'OCCUPIED', patientName: 'Patel, R.', predictedDischargeTime: '32h', assignedNurse: null, riskTier: 'MEDIUM' },
    { bedId: '4W-05', unit: '4-West', status: 'OCCUPIED', patientName: 'Jones, M.', predictedDischargeTime: '8h', assignedNurse: null, riskTier: 'LOW' },
    { bedId: '4W-06', unit: '4-West', status: 'MAINTENANCE', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
    { bedId: '4W-07', unit: '4-West', status: 'OCCUPIED', patientName: 'Nguyen, L.', predictedDischargeTime: '24h', assignedNurse: null, riskTier: 'LOW' },
    { bedId: '4W-08', unit: '4-West', status: 'VACANT', patientName: null, predictedDischargeTime: null, assignedNurse: null, riskTier: null },
  ];

  ngOnInit(): void {
    this.loadBeds();
    this.loadDischargePredictions();
    if (this.canManageSuggestions()) {
      this.loadSuggestions();
      this.subscribeToRealtimeUpdates();
    }
  }

  onDischargePredictionHoursChange(hours: number): void {
    this.dischargePredictionHours.set(hours);
    this.loadDischargePredictions();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private subscribeToRealtimeUpdates(): void {
    this.signalR.taskUpdated$
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => this.loadSuggestions());

    this.signalR.bedStatusChanged$
      .pipe(takeUntil(this.destroy$))
      .subscribe(() => {
        this.loadBeds();
        this.loadSuggestions();
        this.loadDischargePredictions();
      });
  }

  private loadDischargePredictions(): void {
    this.dischargePredictionsLoading.set(true);
    this.bedService.getDischargePredictions(this.dischargePredictionHours())
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: predictions => {
          this.dischargePredictions.set(predictions);
          this.dischargePredictionsLoading.set(false);
        },
        error: err => {
          console.error('Failed to load discharge predictions', err);
          this.dischargePredictionsLoading.set(false);
        },
      });
  }

  private loadSuggestions(): void {
    this.suggestionsLoading.set(true);
    this.bedService.getSuggestions()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: suggestions => {
          this.suggestions.set(suggestions);
          this.suggestionsLoading.set(false);
        },
        error: err => {
          console.error('Failed to load bed suggestions', err);
          this.suggestionsLoading.set(false);
        },
      });
  }

  private loadBeds(): void {
    this.loading.set(true);
    this.error.set(null);

    this.bedService.getBeds(true)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: beds => {
          this.beds.set(beds);
          this.lastUpdated.set(new Date().toLocaleTimeString('en-US', { hour12: false }));
          this.loading.set(false);
        },
        error: err => {
          this.error.set(err.message || 'Failed to load bed board.');
          this.loading.set(false);
        },
      });
  }

  onUnitFilterChange(unit: string): void {
    this.selectedUnit.set(unit);
  }

  onStatusFilterChange(status: string): void {
    this.selectedStatus.set(status);
  }

  onBedClick(bed: BedDto): void {
    this.selectedBed.set(bed);
    this.selectedBedDetail.set(null);
    this.selectedBedDetailLoading.set(true);
    this.bedService.getBedDetails(bed.bedId)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: detail => {
          this.selectedBedDetail.set(detail);
          this.selectedBedDetailLoading.set(false);
        },
        error: err => {
          console.error('Failed to load bed details', err);
          this.selectedBedDetailLoading.set(false);
        },
      });
  }

  onPanelClosed(): void {
    this.selectedBed.set(null);
    this.selectedBedDetail.set(null);
    this.selectedBedDetailLoading.set(false);
  }

  onAssignBed(bed: BedDto): void {
    const waiting = this.selectedBedDetail()?.waiting_patients?.[0];
    if (waiting) {
      this.onAssignWaitingPatient(bed, waiting);
    }
  }

  onAssignWaitingPatient(bed: BedDto, waiting: WaitingPatientForBed): void {
    const suggestion = this.suggestions().find(s => s.task_id === waiting.task_id);
    if (!suggestion) {
      this.error.set('Waiting patient suggestion no longer available.');
      return;
    }
    this.openAssignDialog(suggestion, bed.bedId);
  }

  refresh(): void {
    this.loadBeds();
    this.loadDischargePredictions();
    if (this.canManageSuggestions()) {
      this.loadSuggestions();
    }
  }

  openAssignDialog(suggestion: BedSuggestion, preselectedBedId?: string): void {
    const dialogRef = this.dialog.open(BedSuggestionAssignDialogComponent, {
      width: '480px',
      data: { suggestion, preselectedBedId: preselectedBedId ?? suggestion.best_bed_id },
    });

    dialogRef.afterClosed()
      .pipe(takeUntil(this.destroy$))
      .subscribe(result => {
        if (!result) return;
        this.bedService.assignSuggestion(suggestion.task_id, {
          bed_id: result.bed_id,
          reason: result.reason,
          isolation_confirmed: result.isolation_confirmed,
          notes: result.notes,
        })
          .pipe(takeUntil(this.destroy$))
          .subscribe({
            next: () => {
              this.loadSuggestions();
              this.loadBeds();
            },
            error: err => {
              this.error.set(err.message || 'Failed to assign bed.');
            },
          });
      });
  }

  declineSuggestion(suggestion: BedSuggestion): void {
    const dialogRef = this.dialog.open(BedSuggestionDeclineDialogComponent, {
      data: { patientName: suggestion.patient_name },
    });

    dialogRef.afterClosed()
      .pipe(takeUntil(this.destroy$))
      .subscribe(result => {
        if (!result) return;
        this.bedService.declineSuggestion(suggestion.task_id, result.reason)
          .pipe(takeUntil(this.destroy$))
          .subscribe({
            next: () => this.loadSuggestions(),
            error: err => {
              this.error.set(err.message || 'Failed to decline suggestion.');
            },
          });
      });
  }

  formatWaitingTime(minutes: number | null): string {
    if (minutes === null || minutes < 0) return 'Unknown';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m}m`;
    return `${h}h ${m}m`;
  }

  mapStatusLabel(status: BedStatus): string {
    switch (status) {
      case 'VACANT': return 'Clean';
      case 'OCCUPIED': return 'Occupied';
      case 'DIRTY': return 'Dirty';
      case 'MAINTENANCE': return 'Blocked';
      case 'RESERVED': return 'Blocked';
      default: return status;
    }
  }

  getBedClass(status: BedStatus): string {
    switch (status) {
      case 'VACANT': return 'clean';
      case 'OCCUPIED': return 'occupied';
      case 'DIRTY': return 'dirty';
      case 'MAINTENANCE': return 'blocked';
      case 'RESERVED': return 'blocked';
      default: return 'blocked';
    }
  }

  getRiskClass(tier: string | null): string {
    switch (tier) {
      case 'HIGH': return 'high';
      case 'MEDIUM': return 'med';
      case 'LOW': return 'low';
      default: return '';
    }
  }

  getRiskLabel(tier: string | null): string {
    switch (tier) {
      case 'HIGH': return '0.82 HIGH';
      case 'MEDIUM': return '0.45 MED';
      case 'LOW': return '0.20 LOW';
      default: return '';
    }
  }

  assignBed(bedId: string): void {
    // Legacy no-op; assignment now flows through openAssignDialog.
    console.warn('assignBed is deprecated; use openAssignDialog');
  }

  dismissAlert(): void {
    // Legacy no-op; suggestions are removed after assignment/decline.
  }
}

/**
 * Dialog for confirming a bed assignment from a suggestion.
 * Collects required details: bed selection, reason, isolation confirmation, notes.
 */
@Component({
  selector: 'app-bed-suggestion-assign-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatCheckboxModule,
    MatIconModule,
  ],
  template: `
    <h2 mat-dialog-title>Assign Bed — {{ data.suggestion.patient_name }}</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="assign-form">
        <p class="meta">
          Waiting: <strong>{{ formatWaitingTime(data.suggestion.minutes_waiting) }}</strong> &nbsp;|&nbsp;
          Acuity: <strong>{{ data.suggestion.acuity }}</strong> &nbsp;|&nbsp;
          Current unit: <strong>{{ data.suggestion.current_unit ?? '—' }}</strong>
        </p>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Suggested bed</mat-label>
          <mat-select formControlName="bed_id">
            @for (bed of data.suggestion.suggestions; track bed.bed_id) {
              <mat-option [value]="bed.bed_id">
                {{ bed.bed_number }} ({{ bed.unit }}) — score {{ bed.score | number:'1.2-2' }}
              </mat-option>
            }
          </mat-select>
          <mat-hint>Best-match bed is pre-selected.</mat-hint>
        </mat-form-field>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Reason for assignment</mat-label>
          <textarea matInput formControlName="reason" rows="3" placeholder="Why this bed is appropriate"></textarea>
          @if (form.get('reason')?.hasError('required')) {
            <mat-error>Reason is required.</mat-error>
          }
          @if (form.get('reason')?.hasError('minlength')) {
            <mat-error>Reason must be at least 5 characters.</mat-error>
          }
        </mat-form-field>

        <mat-checkbox formControlName="isolation_confirmed">
          Isolation requirements confirmed
        </mat-checkbox>

        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Notes (optional)</mat-label>
          <textarea matInput formControlName="notes" rows="2"></textarea>
        </mat-form-field>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="null">Cancel</button>
      <button mat-flat-button color="primary" [disabled]="form.invalid" (click)="submit()">Assign Bed</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .assign-form { display: flex; flex-direction: column; gap: 16px; min-width: 360px; }
    .full-width { width: 100%; }
    .meta { font-size: 13px; color: #4b5563; margin: 0 0 8px; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedSuggestionAssignDialogComponent {
  readonly data: { suggestion: BedSuggestion; preselectedBedId: string } = inject(MAT_DIALOG_DATA);
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<BedSuggestionAssignDialogComponent>);
  readonly form: FormGroup = this.fb.group({
    bed_id: [this.data.preselectedBedId, Validators.required],
    reason: ['', [Validators.required, Validators.minLength(5), Validators.maxLength(500)]],
    isolation_confirmed: [false],
    notes: ['', Validators.maxLength(1000)],
  });

  formatWaitingTime(minutes: number | null): string {
    if (minutes === null || minutes < 0) return 'Unknown';
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (h === 0) return `${m}m`;
    return `${h}h ${m}m`;
  }

  submit(): void {
    if (this.form.invalid) return;
    this.dialogRef.close(this.form.value);
  }
}

/**
 * Decline dialog — collects the reason a bed manager is rejecting the suggestion.
 */
@Component({
  selector: 'app-bed-suggestion-decline-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
  ],
  template: `
    <h2 mat-dialog-title>Decline Bed Suggestion</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="decline-form">
        <p class="meta">Patient: <strong>{{ data.patientName }}</strong></p>
        <mat-form-field appearance="outline" class="full-width">
          <mat-label>Reason for declining</mat-label>
          <textarea matInput formControlName="reason" rows="4" placeholder="Explain why this suggestion is not suitable"></textarea>
          <mat-hint align="end">Minimum 5 characters</mat-hint>
          @if (form.get('reason')?.invalid && form.get('reason')?.touched) {
            <mat-error>Reason is required and must be at least 5 characters.</mat-error>
          }
        </mat-form-field>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button [mat-dialog-close]="null">Cancel</button>
      <button mat-flat-button color="warn" [disabled]="form.invalid" (click)="submit()">Decline</button>
    </mat-dialog-actions>
  `,
  styles: [`.decline-form { display: flex; flex-direction: column; gap: 16px; min-width: 360px; } .full-width { width: 100%; } .meta { font-size: 13px; color: #4b5563; margin: 0 0 8px; }`],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedSuggestionDeclineDialogComponent {
  readonly data: { patientName: string } = inject(MAT_DIALOG_DATA);
  private readonly fb = inject(FormBuilder);
  private readonly dialogRef = inject(MatDialogRef<BedSuggestionDeclineDialogComponent>);
  readonly form: FormGroup = this.fb.group({
    reason: ['', [Validators.required, Validators.minLength(5), Validators.maxLength(500)]],
  });

  submit(): void {
    if (this.form.invalid) return;
    this.dialogRef.close(this.form.value);
  }
}
