/**
 * Standalone filter bar for the analytics dashboard.
 *
 * Inputs:
 *   initialFilters — current filter state (from URL query params or defaults)
 *   availableUnits — unit options from app_user.units (JWT claims)
 *
 * Outputs:
 *   filterChange — emits KpiFilterParams when the manager submits new filter values
 *
 * Design refs:
 *   US-061 DoD — MatDateRangePicker; unit dropdown; URL query params
 *   US-061 AC Scenario 1 — pre-set to last 30 days
 *   US-061 AC Scenario 2 — simultaneous chart update on filter apply
 */
import { Component, EventEmitter, Input, OnInit, Output, inject } from '@angular/core';
import { FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatNativeDateModule } from '@angular/material/core';
import { MatSelectModule } from '@angular/material/select';

import { KpiFilterParams } from '../analytics.models';

@Component({
  selector: 'app-analytics-filter-bar',
  standalone: true,
  imports: [
    ReactiveFormsModule,
    MatFormFieldModule,
    MatInputModule,
    MatDatepickerModule,
    MatNativeDateModule,
    MatSelectModule,
    MatButtonModule,
  ],
  templateUrl: './analytics-filter-bar.component.html',
  styleUrl: './analytics-filter-bar.component.scss',
})
export class AnalyticsFilterBarComponent implements OnInit {
  @Input() initialFilters!: KpiFilterParams;
  /** Units the manager can access — derived from app_user.units in the JWT. */
  @Input() availableUnits: string[] = [];

  @Output() filterChange = new EventEmitter<KpiFilterParams>();

  private readonly fb = inject(FormBuilder);

  filterForm!: FormGroup;

  ngOnInit(): void {
    this.filterForm = this.fb.group({
      dateRange: this.fb.group({
        start: [this.parseDate(this.initialFilters.from), Validators.required],
        end: [this.parseDate(this.initialFilters.to), Validators.required],
      }),
      unit: [this.initialFilters.unit ?? null],
    });
  }

  /** Emit the current filter values as KpiFilterParams. */
  applyFilter(): void {
    if (this.filterForm.invalid) return;

    const { dateRange, unit } = this.filterForm.value;
    const filters: KpiFilterParams = {
      from: this.formatDate(dateRange.start),
      to: this.formatDate(dateRange.end),
      unit: unit ?? undefined,
    };
    this.filterChange.emit(filters);
  }

  private parseDate(iso: string): Date {
    return new Date(iso);
  }

  private formatDate(date: Date): string {
    return date.toISOString().split('T')[0];
  }
}
