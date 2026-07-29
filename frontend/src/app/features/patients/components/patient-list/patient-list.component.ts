import {
  Component,
  OnInit,
  OnDestroy,
  inject,
  signal,
  computed,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormControl } from '@angular/forms';
import { Router } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { ScrollingModule } from '@angular/cdk/scrolling';
import {
  Subject,
  debounceTime,
  distinctUntilChanged,
  switchMap,
  catchError,
  of,
  takeUntil,
  startWith,
  combineLatest,
} from 'rxjs';

import { RiskBadgeComponent } from '../../../../shared/components';
import { PatientApiService } from '../../services/patient-api.service';
import { PatientSummary, RiskScoreUpdatedEvent } from '../../models';
import { AuthService } from '../../../../core/auth/auth.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';

/** Columns displayed in MatTable */
const DISPLAYED_COLUMNS = [
  'risk_tier',
  'last_name',
  'first_name',
  'mrn_masked',
  'room_number',
  'admission_date',
  'actions',
];

@Component({
  selector: 'app-patient-list',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatInputModule,
    MatSelectModule,
    MatProgressBarModule,
    MatButtonModule,
    MatIconModule,
    ScrollingModule,
    RiskBadgeComponent,
  ],
  templateUrl: './patient-list.component.html',
  styleUrls: ['./patient-list.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PatientListComponent implements OnInit, OnDestroy {
  private readonly patientApi = inject(PatientApiService);
  private readonly authService = inject(AuthService);
  private readonly signalRService = inject(SignalRService);
  private readonly router = inject(Router);
  private readonly destroy$ = new Subject<void>();

  readonly displayedColumns = DISPLAYED_COLUMNS;

  // --- State signals ---
  readonly patients = signal<PatientSummary[]>([]);
  readonly totalCount = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // --- Form controls ---
  readonly searchControl = new FormControl<string>('', { nonNullable: true });
  readonly unitControl = new FormControl<string>('', { nonNullable: true });

  /** Units available to this nurse from JWT claim */
  readonly availableUnits = signal<string[]>([]);

  currentPage = 0;
  pageSize = 25;

  /** True when >50 rows — enables CDK Virtual Scroll */
  readonly useVirtualScroll = computed(() => this.totalCount() > 50);

  ngOnInit(): void {
    const units = this.authService.getPatientClaim<string[]>('units') ?? [];
    this.availableUnits.set(units);
    this.unitControl.setValue(units[0] ?? '');

    combineLatest([
      this.searchControl.valueChanges.pipe(
        startWith(''),
        debounceTime(300),
        distinctUntilChanged(),
      ),
      this.unitControl.valueChanges.pipe(startWith(units[0] ?? '')),
    ])
      .pipe(
        takeUntil(this.destroy$),
        switchMap(([search, unit]) => {
          this.loading.set(true);
          this.error.set(null);
          this.currentPage = 0;
          return this.patientApi
            .getPatients({ unit, search, page: 1, page_size: this.pageSize })
            .pipe(
              catchError(err => {
                this.error.set('Failed to load patients. Please try again.');
                this.loading.set(false);
                return of(null);
              }),
            );
        }),
      )
      .subscribe(response => {
        if (response) {
          this.patients.set(response.items);
          this.totalCount.set(response.total);
        }
        this.loading.set(false);
      });

    // Subscribe to real-time risk score updates via SignalR
    this.signalRService.riskScoreUpdated$
      .pipe(takeUntil(this.destroy$))
      .subscribe(event => {
        this.patients.update(current =>
          current.map(p =>
            p.encounter_id === event.encounter_id
              ? { ...p, risk_tier: event.risk_tier, risk_score: event.risk_score }
              : p,
          ),
        );
      });
  }

  onPageChange(event: PageEvent): void {
    this.currentPage = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loading.set(true);
    this.error.set(null);

    this.patientApi
      .getPatients({
        unit: this.unitControl.value,
        search: this.searchControl.value,
        page: event.pageIndex + 1,
        page_size: event.pageSize,
      })
      .pipe(
        catchError(() => {
          this.error.set('Failed to load patients. Please try again.');
          this.loading.set(false);
          return of(null);
        }),
        takeUntil(this.destroy$),
      )
      .subscribe(response => {
        if (response) {
          this.patients.set(response.items);
          this.totalCount.set(response.total);
        }
        this.loading.set(false);
      });
  }

  retry(): void {
    this.searchControl.updateValueAndValidity({ emitEvent: true });
  }

  navigateToDetail(encounterId: string): void {
    this.router.navigate(['/patients', encounterId]);
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }
}
