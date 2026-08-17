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

import { PatientSummary } from '../../models';
import { EncountersApiService } from '../../../../core/api/encounters-api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { ActivatedRoute } from '@angular/router';

/** Columns displayed in MatTable */
const DISPLAYED_COLUMNS = [
  'mrn_masked',
  'name',
  'current_unit',
  'updated_at',
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
  private readonly encountersApi = inject(EncountersApiService);
  private readonly authService = inject(AuthService);
  private readonly signalRService = inject(SignalRService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly destroy$ = new Subject<void>();

  readonly displayedColumns = DISPLAYED_COLUMNS;

  // --- State signals ---
  readonly patients = signal<PatientSummary[]>([]);
  readonly totalCount = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);
  readonly filteredPatient = signal<{ patientId: string; name: string } | null>(null);

  // --- Form controls ---
  readonly searchControl = new FormControl<string>('', { nonNullable: true });
  readonly unitControl = new FormControl<string>('', { nonNullable: true });
  readonly statusControl = new FormControl<string>('', { nonNullable: true });

  /** Units available to this nurse from JWT claim */
  readonly availableUnits = signal<string[]>([]);
  readonly availableStatuses = signal<string[]>(['All Status', 'Admitted', 'Discharged', 'Transferred']);

  currentPage = 0;
  pageSize = 25;
  private patientIdFilter = '';

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
    this.availableStatuses.set(['All Status', 'Admitted', 'Discharged', 'Transferred']);
    this.unitControl.setValue('All Units');
    this.statusControl.setValue('All Status');

    // Optional deep-link filter from unique-patients list.
    this.patientIdFilter = this.route.snapshot.queryParamMap.get('patient') ?? '';
    if (this.patientIdFilter) {
      this.filteredPatient.set({
        patientId: this.patientIdFilter,
        name: this.route.snapshot.queryParamMap.get('name') ?? this.patientIdFilter,
      });
    }

    // Load live data from backend on init and when filters change
    this.loadPatients('', 'All Units', 'All Status', this.patientIdFilter);

    // Filter on search/unit/status changes
    combineLatest([
      this.searchControl.valueChanges.pipe(startWith(''), debounceTime(300), distinctUntilChanged()),
      this.unitControl.valueChanges.pipe(startWith('All Units')),
      this.statusControl.valueChanges.pipe(startWith('All Status')),
    ])
      .pipe(takeUntil(this.destroy$))
      .subscribe(([search, unit, status]) => {
        this.loadPatients(search, unit, status, this.patientIdFilter, true);
      });
  }

  private loadPatients(
    search = '',
    unit = 'All Units',
    status = 'All Status',
    patientId = '',
    resetPage = false,
  ): void {
    this.loading.set(true);
    this.error.set(null);

    if (resetPage) {
      this.currentPage = 0;
    }

    const query: import('../../models').PatientListQuery = {
      unit: unit === 'All Units' ? '' : unit,
      search: search.trim() || undefined,
      status: status === 'All Status' ? undefined : status.toUpperCase(),
      page: this.currentPage + 1,
      page_size: this.pageSize,
      patient_id: patientId.trim() || undefined,
    };

    this.encountersApi.listEncounters(query)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: response => {
          this.patients.set(response.items ?? []);
          this.totalCount.set(response.total ?? 0);

          // Derive the patient name from the first matching encounter when it
          // comes via deep-link without a display name.
          const filter = this.filteredPatient();
          if (filter && !filter.name && response.items && response.items.length > 0) {
            const first = response.items[0];
            this.filteredPatient.set({
              patientId: filter.patientId,
              name: `${first.last_name}, ${first.first_name}`,
            });
          }

          this.loading.set(false);
        },
        error: err => {
          this.error.set(err.message || 'Failed to load encounters.');
          this.loading.set(false);
        },
      });
  }

  clearPatientFilter(): void {
    this.patientIdFilter = '';
    this.filteredPatient.set(null);
    this.loadPatients(this.searchControl.value, this.unitControl.value, this.statusControl.value, '');
    this.router.navigate(['/encounters'], { queryParams: {} });
  }

  onPageChange(event: PageEvent): void {
    this.currentPage = event.pageIndex;
    this.pageSize = event.pageSize;
    this.loadPatients(this.searchControl.value, this.unitControl.value, this.statusControl.value, this.patientIdFilter);
  }

  retry(): void {
    this.loadPatients(this.searchControl.value, this.unitControl.value, this.statusControl.value, this.patientIdFilter, false);
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

  getStatusClass(status: string): string {
    switch (status?.toUpperCase()) {
      case 'ADMITTED':
      case 'REGISTERED':
        return 'admitted';
      case 'DISCHARGED':
        return 'discharging';
      case 'TRANSFERRED':
        return 'transferred';
      default:
        return 'admitted';
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

  getDateValue(patient: PatientSummary): string {
    const status = patient.status?.toUpperCase();
    if (status === 'ADMITTED') {
      return patient.admission_date || '';
    }
    return patient.updated_at || patient.admission_date || '';
  }

}
