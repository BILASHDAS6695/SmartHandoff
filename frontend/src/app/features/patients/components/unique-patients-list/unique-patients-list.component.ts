import {
  Component,
  OnInit,
  OnDestroy,
  inject,
  signal,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormControl } from '@angular/forms';
import { Router } from '@angular/router';
import { MatTableModule } from '@angular/material/table';
import { MatPaginatorModule, PageEvent } from '@angular/material/paginator';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import {
  Subject,
  debounceTime,
  distinctUntilChanged,
  takeUntil,
  startWith,
} from 'rxjs';

import { PatientApiService } from '../../services/patient-api.service';
import { UniquePatientSummary } from '../../models';

/** Columns displayed in the unique patients MatTable. */
const DISPLAYED_COLUMNS = [
  'mrn_masked',
  'name',
  'date_of_birth',
  'active_encounters',
  'latest_status',
  'actions',
];

/** Active encounter statuses used for display helpers. */
const ACTIVE_STATUSES = ['REGISTERED', 'PRE_ADMISSION', 'ADMITTED', 'TRANSFERRED'];

/**
 * UniquePatientsListComponent — shows one row per real patient.
 *
 * The legacy patient list endpoint returns one row per encounter/registration,
 * which creates the appearance of duplicate patients. This component uses
 * ``GET /api/v1/patients?unique=true`` to de-duplicate by patient identity.
 */
@Component({
  selector: 'app-unique-patients-list',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatTableModule,
    MatPaginatorModule,
    MatInputModule,
    MatProgressBarModule,
    MatButtonModule,
    MatIconModule,
  ],
  templateUrl: './unique-patients-list.component.html',
  styleUrls: ['./unique-patients-list.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UniquePatientsListComponent implements OnInit, OnDestroy {
  private readonly patientApi = inject(PatientApiService);
  private readonly router = inject(Router);
  private readonly destroy$ = new Subject<void>();

  readonly displayedColumns = DISPLAYED_COLUMNS;

  // --- State signals ---
  readonly patients = signal<UniquePatientSummary[]>([]);
  readonly totalCount = signal<number>(0);
  readonly loading = signal<boolean>(false);
  readonly error = signal<string | null>(null);

  // --- Form controls ---
  readonly searchControl = new FormControl<string>('', { nonNullable: true });

  currentPage = 0;
  pageSize = 25;

  ngOnInit(): void {
    this.loadPatients();

    this.searchControl.valueChanges
      .pipe(
        startWith(''),
        debounceTime(300),
        distinctUntilChanged(),
        takeUntil(this.destroy$),
      )
      .subscribe(() => {
        this.currentPage = 0;
        this.loadPatients();
      });
  }

  private loadPatients(): void {
    this.loading.set(true);
    this.error.set(null);

    const query = {
      unit: '',
      search: this.searchControl.value.trim() || undefined,
      page: this.currentPage + 1,
      page_size: this.pageSize,
      unique: true as const,
    };

    this.patientApi.getPatients(query)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: response => {
          this.patients.set(response.items ?? []);
          this.totalCount.set(response.total ?? 0);
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
    this.loadPatients();
  }

  retry(): void {
    this.loadPatients();
  }

  navigateToPatient(patient: UniquePatientSummary): void {
    // Unique patients do not have a dedicated detail page yet; navigate to the
    // encounters list filtered to this patient so the user can pick the relevant
    // registration/admission episode.
    this.router.navigate(['/encounters'], {
      queryParams: {
        patient: patient.patient_id,
        name: `${patient.last_name}, ${patient.first_name}`,
      },
    });
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

  getFullName(patient: UniquePatientSummary): string {
    return `${patient.last_name}, ${patient.first_name}`;
  }

  getStatusClass(status: string): string {
    switch (status?.toUpperCase()) {
      case 'ADMITTED':
      case 'REGISTERED':
      case 'PRE_ADMISSION':
        return 'admitted';
      case 'DISCHARGED':
        return 'discharging';
      case 'TRANSFERRED':
        return 'transferred';
      default:
        return 'admitted';
    }
  }

  isActiveStatus(status: string): boolean {
    return ACTIVE_STATUSES.includes(status?.toUpperCase());
  }
}
