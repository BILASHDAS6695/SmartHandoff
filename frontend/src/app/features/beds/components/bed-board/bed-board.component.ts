import { Component, OnInit, signal, inject, ChangeDetectionStrategy, OnDestroy, computed } from '@angular/core';
import { CommonModule, Location } from '@angular/common';
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
import { ActivatedRoute, Router } from '@angular/router';
import { v4 as uuidv4 } from 'uuid';
import { BedDetailPanelComponent } from '../bed-detail-panel/bed-detail-panel.component';
import { BedDetailDto, BedDto, BedStatus, BedSuggestion, DischargePredictionDto, WaitingPatientForBed } from '../../models/bed.model';
import { BedBoardService } from '../../services/bed-board.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { NotificationService } from '../../../../core/notifications/notification.service';

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
  private readonly notificationService = inject(NotificationService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly location = inject(Location);
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
  readonly actionLoading = signal(false);
  readonly actionLoadingTaskId = signal<string | null>(null);
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
  readonly dischargePredictionOptions = signal<number[]>([4, 8, 12, 24,48, 120]);
  readonly dischargePredictions = signal<DischargePredictionDto[]>([]);
  readonly dischargePredictionsLoading = signal(false);
  readonly dischargePredictionsPage = signal<number>(1);
  readonly dischargePredictionsPageSize = signal<number>(10);

  readonly dischargePredictionsTotalPages = computed(() =>
    Math.max(1, Math.ceil(this.dischargePredictions().length / this.dischargePredictionsPageSize()))
  );

  readonly pagedDischargePredictions = computed(() => {
    const start = (this.dischargePredictionsPage() - 1) * this.dischargePredictionsPageSize();
    return this.dischargePredictions().slice(start, start + this.dischargePredictionsPageSize());
  });

  private readonly pendingAssignQuery = signal<{ taskId?: string; encounterId?: string; notificationId?: string } | null>(null);

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
      this.subscribeToAssignDeepLink();
    }
  }

  onDischargePredictionHoursChange(hours: number): void {
    this.dischargePredictionHours.set(hours);
    this.dischargePredictionsPage.set(1);
    this.loadDischargePredictions();
  }

  setDischargePredictionsPage(page: number): void {
    if (page >= 1 && page <= this.dischargePredictionsTotalPages()) {
      this.dischargePredictionsPage.set(page);
    }
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  private subscribeToAssignDeepLink(): void {
    this.route.queryParams
      .pipe(takeUntil(this.destroy$))
      .subscribe(params => {
        if (params['openAssign'] === 'true') {
          this.pendingAssignQuery.set({
            taskId: params['taskId'] || undefined,
            encounterId: params['encounterId'] || undefined,
            notificationId: params['notificationId'] || undefined,
          });
          // Remove the query params so a refresh does not reopen the dialog.
          void this.router.navigate([], {
            relativeTo: this.route,
            queryParams: {},
            replaceUrl: true,
          });
          this.tryOpenAssignFromQuery();
        }
      });
  }

  private tryOpenAssignFromQuery(): void {
    const query = this.pendingAssignQuery();
    if (!query) return;

    const suggestions = this.suggestions();
    if (!suggestions.length && this.suggestionsLoading()) return;

    let suggestion: BedSuggestion | undefined;
    if (query.taskId) {
      suggestion = suggestions.find(s => s.task_id === query.taskId);
    } else if (query.encounterId) {
      suggestion = suggestions.find(s => s.encounter_id === query.encounterId);
    } else {
      suggestion = suggestions[0];
    }

    this.pendingAssignQuery.set(null);

    if (suggestion) {
      this.openAssignDialog(suggestion);
    } else if (query.notificationId) {
      // The suggestion was already actioned or is no longer available; mark the
      // originating notification as read instead of showing an error banner.
      this.notificationService.markAsRead(query.notificationId);
    } else {
      // Defensive: older notifications may not carry notificationId; mark by key.
      const key = query.taskId
        ? `bed-suggestion-${query.taskId}`
        : query.encounterId
          ? `bed-suggestion-${query.encounterId}`
          : undefined;
      if (key) {
        const stale = this.notificationService.notifications().find((n) => n.key === key);
        if (stale) {
          this.notificationService.markAsRead(stale.id);
        }
      }
    }
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

    this.signalR.bedSuggestionCreated$
      .pipe(takeUntil(this.destroy$))
      .subscribe((suggestion) => {
        const taskId = suggestion.taskId ?? suggestion.task_id ?? '';
        const encounterId = suggestion.encounterId ?? suggestion.encounter_id ?? '';
        const name = suggestion.patientName ?? suggestion.patient_name ?? 'A patient';
        const unit = suggestion.patientUnit ?? suggestion.patient_unit ?? 'Unknown unit';
        const bed = suggestion.bestBedNumber ?? suggestion.best_bed_number ?? suggestion.bedId ?? suggestion.bed_id ?? '';

        // Fallback notification in case the NotificationService watcher misses
        // the event (e.g., transient subscription timing or group membership).
        // key-based deduplication prevents double notifications when both fire.
        const fallbackId = uuidv4();
        this.notificationService.add({
          id: fallbackId,
          title: 'ED Boarding Bed Suggestion',
          message: `${name} · Recommended bed ${bed} in ${unit}`,
          tone: 'info',
          route: '/beds',
          key: taskId ? `bed-suggestion-${taskId}` : `bed-suggestion-${encounterId}`,
          queryParams: {
            openAssign: 'true',
            taskId,
            encounterId,
            notificationId: fallbackId,
          },
        });

        this.suggestions.update((current) => {
          const exists = current.some((s) => s.task_id === taskId);
          if (exists) return current;
          const bedId = suggestion.bedId ?? suggestion.bed_id ?? '';
          const bestBedNumber = suggestion.bestBedNumber ?? suggestion.best_bed_number ?? bedId;
          const suggestionUnit = suggestion.patientUnit ?? suggestion.patient_unit ?? 'Unknown';
          const fallbackSuggestion: BedSuggestion['suggestions'][number] = {
            bed_id: bedId,
            bed_number: bestBedNumber,
            unit: suggestionUnit,
            room: '',
            score: 1,
            score_breakdown: {
              acuity_match: 1,
              care_type_match: 1,
              isolation_match: 1,
              gender_match: 1,
            },
          };
          const next: BedSuggestion = {
            task_id: taskId,
            encounter_id: encounterId,
            patient_name: name,
            patient_id: suggestion.patientId ?? suggestion.patient_id,
            current_unit: suggestionUnit,
            acuity: suggestion.acuity ?? 'Unknown',
            minutes_waiting: suggestion.minutesWaiting ?? suggestion.minutes_waiting ?? null,
            best_bed_id: bedId,
            best_bed_number: bestBedNumber,
            best_bed_unit: suggestionUnit,
            receivedAt: Date.now(),
            suggestions: suggestion.suggestions?.map((s) => ({
              bed_id: s.bed_id,
              bed_number: s.bed_number,
              unit: s.unit,
              room: s.room ?? '',
              score: s.score ?? 0,
              score_breakdown: {
                acuity_match: 1,
                care_type_match: 1,
                isolation_match: 1,
                gender_match: 1,
              },
            })) ?? [fallbackSuggestion],
          };
          return [next, ...current];
        });
        this.loadSuggestions();
      });

    this.signalR.boardingAlertCreated$
      .pipe(takeUntil(this.destroy$))
      .subscribe((alert) => {
        const minutes = alert.minutesElapsed ?? alert.minutes_elapsed ?? 0;
        const unit = alert.patientUnit ?? alert.patient_unit ?? 'ED';
        const tone: 'error' | 'warning' =
          alert.severity === 'CRITICAL' || alert.severity === 'HIGH' ? 'error' : 'warning';
        const encounterId = alert.encounterId ?? alert.encounter_id ?? '';
        const boardingFallbackId = uuidv4();
        this.notificationService.add({
          id: boardingFallbackId,
          title: alert.title || 'ED Boarding Alert',
          message: alert.message || `Patient in ${unit} has been waiting ${minutes} minutes.`,
          tone,
          route: '/beds',
          key: encounterId ? `boarding-alert-${encounterId}` : `boarding-alert-${alert.alertId ?? alert.alert_id}`,
          queryParams: encounterId
            ? { openAssign: 'true', encounterId, notificationId: boardingFallbackId }
            : { openAssign: 'true', notificationId: boardingFallbackId },
        });
        this.loadBeds();
        this.loadSuggestions();
      });
  }

  private loadDischargePredictions(): void {
    this.dischargePredictionsLoading.set(true);
    this.bedService.getDischargePredictions(this.dischargePredictionHours())
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: predictions => {
          this.dischargePredictions.set(predictions);
          this.dischargePredictionsPage.set(1);
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
          // Merge with any pending action item to avoid the card disappearing
          // while the assign/decline API call is still in flight.
          const pendingTaskId = this.actionLoadingTaskId();
          const pending = pendingTaskId
            ? this.suggestions().find((s) => s.task_id === pendingTaskId)
            : undefined;

          // Also keep SignalR-injected suggestions that arrived recently (within
          // the last 30 seconds) but have not yet persisted to the backend API.
          // This prevents the "No pending ED boarding alerts" card from flashing
          // while the agent suggestion is still being processed.
          const now = Date.now();
          const recentSignalR = this.suggestions().filter(
            (s) =>
              s.receivedAt &&
              now - s.receivedAt < 30000 &&
              !suggestions.some((api) => api.task_id === s.task_id),
          );

          const merged = [
            ...(pending && !suggestions.some((s) => s.task_id === pending.task_id) ? [pending] : []),
            ...recentSignalR,
            ...suggestions,
          ];
          this.suggestions.set(merged);
          this.suggestionsLoading.set(false);
          this.tryOpenAssignFromQuery();
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

  goBack(): void {
    this.location.back();
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
        this.setActionLoading(suggestion.task_id, true);
        this.bedService.assignSuggestion(suggestion.task_id, {
          bed_id: result.bed_id,
          reason: result.reason,
          isolation_confirmed: result.isolation_confirmed,
          notes: result.notes,
        })
          .pipe(takeUntil(this.destroy$))
          .subscribe({
            next: () => {
              this.setActionLoading(null, false);
              this.loadSuggestions();
              this.loadBeds();
              this.loadDischargePredictions();
            },
            error: err => {
              this.setActionLoading(null, false);
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
        this.setActionLoading(suggestion.task_id, true);
        this.bedService.declineSuggestion(suggestion.task_id, result.reason)
          .pipe(takeUntil(this.destroy$))
          .subscribe({
            next: () => {
              this.setActionLoading(null, false);
              this.loadSuggestions();
              this.loadBeds();
            },
            error: err => {
              this.setActionLoading(null, false);
              this.error.set(err.message || 'Failed to decline suggestion.');
            },
          });
      });
  }

  isActionLoading(taskId: string): boolean {
    return this.actionLoading() && this.actionLoadingTaskId() === taskId;
  }

  private setActionLoading(taskId: string | null, loading: boolean): void {
    this.actionLoadingTaskId.set(taskId);
    this.actionLoading.set(loading);
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
