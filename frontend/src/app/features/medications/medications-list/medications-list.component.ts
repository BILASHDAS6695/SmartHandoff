import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MedicationApiService, MedicationReconciliationResult } from '../services/medication-api.service';

/**
 * Medications List Component — displays all medications from the backend.
 *
 * Route: /medications
 * API: GET /api/v1/medications
 */
@Component({
  selector: 'app-medications-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatProgressSpinnerModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
  ],
  templateUrl: './medications-list.component.html',
  styleUrls: ['./medications-list.component.scss'],
})
export class MedicationsListComponent implements OnInit {
  private readonly medicationApi = inject(MedicationApiService);

  readonly medications = signal<MedicationReconciliationResult[]>([]);
  readonly isLoading = signal(true);
  readonly hasError = signal(false);
  readonly displayedColumns: string[] = [
    'name',
    'dose',
    'route',
    'frequency',
    'category',
    'sources',
    'flags',
    'severity',
  ];

  ngOnInit(): void {
    this.loadMedications();
  }

  loadMedications(): void {
    this.isLoading.set(true);
    this.hasError.set(false);
    this.medicationApi.getAllMedications().subscribe({
      next: (response) => {
        this.medications.set(response.medications ?? []);
        this.isLoading.set(false);
      },
      error: () => {
        this.hasError.set(true);
        this.isLoading.set(false);
      },
    });
  }

  getSources(med: MedicationReconciliationResult): string[] {
    const sources: string[] = [];
    if (med.pre_admit) sources.push('Pre-Admit');
    if (med.inpatient) sources.push('Inpatient');
    if (med.discharge) sources.push('Discharge');
    return sources;
  }

  getSeverityClass(severity: string | null): string {
    switch (severity) {
      case 'HIGH': return 'severity-high';
      case 'MEDIUM': return 'severity-medium';
      case 'LOW': return 'severity-low';
      default: return 'severity-none';
    }
  }
}
