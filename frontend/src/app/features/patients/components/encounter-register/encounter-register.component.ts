import { Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { EncountersApiService } from '@core/api';
import { ToastService } from '@core/notifications/toast.service';
import { PatientApiService } from '../../services/patient-api.service';
import { PatientSummary } from '../../models';

/**
 * EncounterRegisterComponent — standalone page for registering a new encounter.
 *
 * Accessible from the main sidebar. Allows searching for an existing patient
 * and creating an encounter linked to that patient.
 */
@Component({
  selector: 'app-encounter-register',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatIconModule,
    MatButtonModule,
    MatInputModule,
    MatSelectModule,
    MatFormFieldModule,
    MatProgressSpinnerModule,
  ],
  templateUrl: './encounter-register.component.html',
  styleUrl: './encounter-register.component.scss',
})
export class EncounterRegisterComponent {
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);
  private readonly patientApi = inject(PatientApiService);
  private readonly encountersApi = inject(EncountersApiService);
  private readonly toast = inject(ToastService);

  readonly registerForm: FormGroup = this.fb.group({
    patient_id: ['', Validators.required],
    first_name: ['', Validators.required],
    last_name: ['', Validators.required],
    date_of_birth: ['', Validators.required],
    mrn: [''],
    unit: ['', Validators.required],
    status: ['REGISTERED', Validators.required],
    risk_tier: ['UNKNOWN', Validators.required],
    event_type: ['A04'],
  });

  readonly searchQuery = signal<string>('');
  readonly searchResults = signal<PatientSummary[]>([]);
  readonly isSearching = signal<boolean>(false);
  readonly searchError = signal<string | null>(null);
  readonly selectedSearchPatient = signal<PatientSummary | null>(null);
  readonly isRegistering = signal<boolean>(false);
  readonly registerError = signal<string | null>(null);
  readonly registrationSuccess = signal<boolean>(false);

  readonly statusOptions = ['REGISTERED', 'PRE_ADMISSION', 'ADMITTED', 'TRANSFERRED', 'DISCHARGED'];
  readonly riskTierOptions = ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'];
  readonly eventTypeOptions = [
    { value: 'A04', label: 'A04 - Registration' },
    { value: 'A01', label: 'A01 - Admit' },
    { value: 'A02', label: 'A02 - Transfer' },
    { value: 'A03', label: 'A03 - Discharge' },
    { value: 'A08', label: 'A08 - Update' },
  ];

  onSearchPatients(): void {
    const query = this.searchQuery().trim();
    if (!query) {
      this.searchResults.set([]);
      return;
    }
    this.isSearching.set(true);
    this.searchError.set(null);
    this.patientApi
      .getPatients({ unit: 'ICU', search: query, page: 1, page_size: 25 })
      .subscribe({
        next: (response) => {
          this.searchResults.set(response.items ?? []);
          this.isSearching.set(false);
        },
        error: (err: Error) => {
          this.searchError.set(err.message);
          this.isSearching.set(false);
        },
      });
  }

  selectSearchPatient(patient: PatientSummary): void {
    this.selectedSearchPatient.set(patient);
    this.registerForm.patchValue({
      patient_id: patient.patient_id,
      first_name: patient.first_name,
      last_name: patient.last_name,
      date_of_birth: patient.date_of_birth,
      mrn: patient.mrn_masked,
      unit: patient.current_unit || '',
    });
  }

  clearSelectedSearchPatient(): void {
    this.selectedSearchPatient.set(null);
    this.registerForm.reset({
      patient_id: '',
      first_name: '',
      last_name: '',
      date_of_birth: '',
      mrn: '',
      unit: '',
      status: 'REGISTERED',
      risk_tier: 'UNKNOWN',
      event_type: 'A04',
    });
  }

  onRegisterEncounter(): void {
    if (this.registerForm.invalid) {
      this.registerForm.markAllAsTouched();
      return;
    }

    this.isRegistering.set(true);
    this.registerError.set(null);
    this.registrationSuccess.set(false);

    const payload = {
      patient_id: this.registerForm.value.patient_id,
      status: this.registerForm.value.status,
      unit: this.registerForm.value.unit,
      risk_tier: this.registerForm.value.risk_tier,
      event_type: this.registerForm.value.event_type || null,
    };

    this.encountersApi.createEncounter(payload).subscribe({
      next: (encounter) => {
        this.isRegistering.set(false);
        this.registrationSuccess.set(true);
        this.toast.success(`Encounter registered: ${encounter.id}`);
        this.router.navigate(['/patients', encounter.id]);
      },
      error: (err: Error) => {
        this.isRegistering.set(false);
        this.registerError.set(err.message);
        this.toast.error(`Failed to register encounter: ${err.message}`);
      },
    });
  }

  goBack(): void {
    this.router.navigate(['/patients']);
  }
}
