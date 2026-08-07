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
import { FormsModule, ReactiveFormsModule, FormControl } from '@angular/forms';
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

import { PatientApiService } from '../../services/patient-api.service';
import { PatientSummary, RiskScoreUpdatedEvent } from '../../models';
import { AuthService } from '../../../../core/auth/auth.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';

/** Columns displayed in MatTable */
const DISPLAYED_COLUMNS = [
  'mrn_masked',
  'name',
  'current_unit',
  'admission_date',
  'status',
  'risk_score',
  'actions',
];

@Component({
  selector: 'app-patient-list',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatInputModule,
    MatSelectModule,
    MatProgressBarModule,
    MatButtonModule,
    MatIconModule,
    ScrollingModule,
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
  readonly statusControl = new FormControl<string>('', { nonNullable: true });

  /** Units available to this nurse from JWT claim */
  readonly availableUnits = signal<string[]>([]);
  readonly availableStatuses = signal<string[]>(['All Status', 'Admitted', 'Discharging', 'Transferred']);

  currentPage = 0;
  pageSize = 25;

  /** True when >50 rows — enables CDK Virtual Scroll */
  readonly useVirtualScroll = computed(() => this.totalCount() > 50);

  // --- Revealed MRN state ---
  readonly revealedMrns = signal<Set<string>>(new Set());

  toggleMrn(patientId: string): void {
    this.revealedMrns.update(set => {
      const next = new Set(set);
      if (next.has(patientId)) {
        next.delete(patientId);
      } else {
        next.add(patientId);
      }
      return next;
    });
  }

  getMrnDisplay(patient: PatientSummary): string {
    return this.revealedMrns().has(patient.patient_id) ? patient.patient_id : patient.mrn_masked;
  }

  isMrnRevealed(patientId: string): boolean {
    return this.revealedMrns().has(patientId);
  }

  ngOnInit(): void {
    const user = this.authService.currentUser();
    const units = user?.units?.length ? user.units : ['All Units'];
    this.availableUnits.set(['All Units', ...units.filter(u => u !== 'All Units')]);
    this.availableStatuses.set(['All Status', 'Admitted', 'Discharging', 'Transferred']);
    this.unitControl.setValue('All Units');
    this.statusControl.setValue('All Status');

    // Load live data from backend on init and when filters change
    this.loadPatients();

    // Filter on search/unit/status changes
    combineLatest([
      this.searchControl.valueChanges.pipe(startWith(''), debounceTime(300), distinctUntilChanged()),
      this.unitControl.valueChanges.pipe(startWith('All Units')),
      this.statusControl.valueChanges.pipe(startWith('All Status')),
    ])
      .pipe(takeUntil(this.destroy$))
      .subscribe(([search, unit, status]) => {
        this.loadPatients(search, unit, status, true);
      });
  }

  private loadPatients(search = '', unit = 'All Units', status = 'All Status', resetPage = false): void {
    this.loading.set(true);
    this.error.set(null);

    if (resetPage) {
      this.currentPage = 0;
    }

    const queryUnit = unit === 'All Units' ? 'ICU' : unit; // Backend requires a concrete unit
    const query: import('../../models').PatientListQuery = {
      unit: queryUnit,
      search: search.trim() || undefined,
      page: this.currentPage + 1,
      page_size: this.pageSize,
    };

    this.patientApi.getPatients(query)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: response => {
          let items = response.items ?? [];
          // Apply client-side status filter since backend does not support it
          if (status !== 'All Status') {
            items = items.filter(p => this.getStatus(p) === status);
          }
          this.patients.set(items);
          this.totalCount.set(response.total ?? items.length);
          this.loading.set(false);
        },
        error: err => {
          this.error.set(err.message || 'Failed to load patients.');
          this.loading.set(false);
        },
      });
  }

  onPageChange(event: PageEvent): void {
    this.currentPage = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadPatients(this.searchControl.value, this.unitControl.value, this.statusControl.value);
  }

  retry(): void {
    this.loadPatients(this.searchControl.value, this.unitControl.value, this.statusControl.value, false);
  }

  navigateToDetail(encounterId: string): void {
    this.router.navigate(['/patients', encounterId]);
  }

  getStartIndex(): number {
    return this.totalCount() === 0 ? 0 : this.currentPage * this.pageSize + 1;
  }

  getEndIndex(): number {
    return Math.min((this.currentPage + 1) * this.pageSize, this.totalCount());
  }

  getTotalPages(): number {
    return Math.ceil(this.totalCount() / this.pageSize);
  }

  getPageNumbers(): number[] {
    const total = this.getTotalPages();
    if (total <= 6) {
      return Array.from({ length: total }, (_, i) => i + 1);
    }
    const current = this.currentPage + 1;
    if (current <= 3) {
      return [1, 2, 3, 4, 5, -1, total];
    }
    if (current >= total - 2) {
      return [1, -1, total - 4, total - 3, total - 2, total - 1, total];
    }
    return [1, -1, current - 1, current, current + 1, -1, total];
  }

  goToPage(pageIndex: number): void {
    if (pageIndex < 0 || pageIndex >= this.getTotalPages()) return;
    this.onPageChange({ pageIndex, pageSize: this.pageSize, length: this.totalCount() } as PageEvent);
  }

  onPageSizeChange(newSize: number): void {
    this.pageSize = newSize;
    this.currentPage = 0;
    this.onPageChange({ pageIndex: 0, pageSize: newSize, length: this.totalCount() } as PageEvent);
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  getStatus(patient: PatientSummary): string {
    // Derive status from risk tier for wireframe demo; backend may provide real status later
    if (patient.risk_tier === 'HIGH') return 'Discharging';
    if (patient.risk_tier === 'MEDIUM') return 'Admitted';
    return 'Transferred';
  }

  getStatusClass(status: string): string {
    switch (status) {
      case 'Admitted': return 'admitted';
      case 'Discharging': return 'discharging';
      case 'Transferred': return 'transferred';
      default: return 'admitted';
    }
  }

  getRiskBarWidth(score: number | null): string {
    if (score === null || score === undefined) return '0%';
    return `${Math.round(score * 100)}%`;
  }

  getRiskClass(tier: string): string {
    switch (tier) {
      case 'HIGH': return 'high';
      case 'MEDIUM': return 'med';
      case 'LOW': return 'low';
      default: return 'low';
    }
  }

  getRiskLabel(tier: string): string {
    switch (tier) {
      case 'HIGH': return 'HIGH';
      case 'MEDIUM': return 'MED';
      case 'LOW': return 'LOW';
      default: return 'LOW';
    }
  }

  getFullName(patient: PatientSummary): string {
    return `${patient.last_name}, ${patient.first_name}`;
  }

  getRiskIcon(tier: string): string {
    switch (tier) {
      case 'HIGH': return '⚠';
      case 'MEDIUM': return '▲';
      case 'LOW': return '✓';
      default: return '✓';
    }
  }

  private filterByStatus(patients: PatientSummary[], status: string): PatientSummary[] {
    if (!patients || status === 'All Status') {
      return patients;
    }
    return patients.filter(patient => this.getStatus(patient) === status);
  }
}
