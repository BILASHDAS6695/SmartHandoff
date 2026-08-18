import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormBuilder, FormGroup, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTableModule } from '@angular/material/table';
import { EncountersApiService } from '@core/api';
import { ToastService } from '@core/notifications/toast.service';
import { AuthService } from '@core/auth/auth.service';
import { PatientApiService } from '../../services/patient-api.service';
import { UniquePatientSummary } from '../../models';

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
    MatTableModule,
  ],
  templateUrl: './encounter-register.component.html',
  styleUrl: './encounter-register.component.scss',
})
export class EncounterRegisterComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);
  private readonly patientApi = inject(PatientApiService);
  private readonly encountersApi = inject(EncountersApiService);
  private readonly authService = inject(AuthService);
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
  readonly searchResults = signal<UniquePatientSummary[]>([]);
  readonly isSearching = signal<boolean>(false);
  readonly searchError = signal<string | null>(null);
  readonly selectedSearchPatient = signal<UniquePatientSummary | null>(null);
  readonly isRegistering = signal<boolean>(false);
  readonly registerError = signal<string | null>(null);
  readonly registrationSuccess = signal<boolean>(false);
  readonly isLoading = computed(() => this.isSearching() || this.isRegistering());

  readonly searchResultColumns = ['name', 'dob', 'mrn', 'active_encounters', 'actions'];

  readonly riskTierOptions = ['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'];

  /** Units the current user is assigned to (from JWT). */
  readonly availableUnits = computed(() => {
    const units = this.authService.currentUser()?.units ?? [];
    return units.length > 0 ? units : ['ICU', '3N', 'ED', '2A'];
  });

  /** True when the selected patient already has an active encounter. */
  readonly hasActiveEncounter = computed(() =>
    (this.selectedSearchPatient()?.active_encounter_count ?? 0) > 0
  );

  readonly activeEncounterId = computed(() =>
    this.selectedSearchPatient()?.active_encounter_id ?? null
  );

  readonly activeEncounterStatus = computed(() =>
    this.selectedSearchPatient()?.latest_status?.toUpperCase() ?? ''
  );

  /** Submit label changes based on create vs update flow. */
  readonly submitLabel = computed(() => {
    if (this.isRegistering()) return this.hasActiveEncounter() ? 'Updating…' : 'Registering…';
    if (!this.hasActiveEncounter()) return 'Register Encounter';
    return ['REGISTERED', 'PRE_ADMISSION'].includes(this.activeEncounterStatus())
      ? 'Admit Patient'
      : 'Update Encounter';
  });

  /** Dynamic status options based on whether the patient already has an active encounter. */
  readonly statusOptions = computed(() => {
    const patient = this.selectedSearchPatient();
    if (!patient) return ['REGISTERED', 'PRE_ADMISSION', 'ADMITTED', 'TRANSFERRED', 'DISCHARGED'];

    if (!this.hasActiveEncounter()) return ['REGISTERED', 'PRE_ADMISSION', 'ADMITTED'];

    switch (this.activeEncounterStatus()) {
      case 'REGISTERED':
      case 'PRE_ADMISSION':
        return ['ADMITTED'];
      case 'ADMITTED':
        return ['TRANSFERRED', 'DISCHARGED'];
      case 'TRANSFERRED':
        return ['DISCHARGED'];
      default:
        return [];
    }
  });

  /** Dynamic ADT event type options based on whether the patient already has an active encounter. */
  readonly eventTypeOptions = computed(() => {
    const patient = this.selectedSearchPatient();
    if (!patient) {
      return [
        { value: 'A04', label: 'A04 - Registration' },
        { value: 'A01', label: 'A01 - Admit' },
        { value: 'A02', label: 'A02 - Transfer' },
        { value: 'A03', label: 'A03 - Discharge' },
      ];
    }

    if (!this.hasActiveEncounter()) {
      return [
          { value: 'A04', label: 'A04 - Registration' },
          { value: 'A01', label: 'A01 - Admit' },
      ];
    }

    switch (this.activeEncounterStatus()) {
      case 'REGISTERED':
      case 'PRE_ADMISSION':
        return [{ value: 'A01', label: 'A01 - Admit' }];
      case 'ADMITTED':
        return [
          { value: 'A02', label: 'A02 - Transfer' },
          { value: 'A03', label: 'A03 - Discharge' },
        ];
      case 'TRANSFERRED':
        return [{ value: 'A03', label: 'A03 - Discharge' }];
      default:
        return [];
    }
  });

  ngOnInit(): void {
    const encounterId = this.route.snapshot.queryParamMap.get('encounter');
    if (encounterId) {
      this.loadEncounterForManagement(encounterId);
    }
  }

  private loadEncounterForManagement(encounterId: string): void {
    this.isSearching.set(true);
    this.searchError.set(null);
    this.patientApi.getPatientByEncounter(encounterId).subscribe({
      next: (encounter) => {
        const patient: UniquePatientSummary = {
          patient_id: encounter.patient_id,
          mrn_masked: encounter.mrn_masked,
          first_name: encounter.first_name,
          last_name: encounter.last_name,
          date_of_birth: encounter.date_of_birth,
          active_encounter_count: 1,
          active_encounter_id: encounter.encounter_id,
          latest_status: encounter.status,
          latest_risk_tier: encounter.risk_tier,
        };
        this.searchResults.set([patient]);
        this.selectSearchPatient(patient);
        this.isSearching.set(false);
      },
      error: (err: Error) => {
        this.searchError.set(err.message || 'Failed to load encounter for management.');
        this.isSearching.set(false);
      },
    });
  }

  onSearchPatients(): void {
    const query = this.searchQuery().trim();
    if (!query) {
      this.searchResults.set([]);
      this.selectedSearchPatient.set(null);
      this.registerError.set(null);
      this._resetFormToDefaults();
      return;
    }
    this.isSearching.set(true);
    this.searchError.set(null);
    this.patientApi
      .getPatients({ unit: '', search: query, page: 1, page_size: 25, unique: true })
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

  selectSearchPatient(patient: UniquePatientSummary): void {
    this.registerError.set(null);

    // Reset to a clean slate first so stale values and validation state don't survive.
    this._resetFormToDefaults();
    this.selectedSearchPatient.set(patient);

    // Default status/ADT type depends on whether the patient already has an active encounter.
    const encounterStatus = patient.latest_status?.toUpperCase();
    const nextStatus = encounterStatus === 'REGISTERED' || encounterStatus === 'PRE_ADMISSION'
      ? 'ADMITTED'
      : encounterStatus === 'ADMITTED'
        ? 'TRANSFERRED'
        : encounterStatus === 'TRANSFERRED'
          ? 'DISCHARGED'
          : 'REGISTERED';
    const nextEventType = nextStatus === 'ADMITTED'
      ? 'A01'
      : nextStatus === 'TRANSFERRED'
        ? 'A02'
        : nextStatus === 'DISCHARGED'
          ? 'A03'
          : 'A04';

    // Patch after a tick so computed option lists have propagated to the template.
    setTimeout(() => {
      this.registerForm.patchValue({
        patient_id: patient.patient_id,
        first_name: patient.first_name,
        last_name: patient.last_name,
        date_of_birth: patient.date_of_birth,
        mrn: patient.mrn_masked,
        unit: this.availableUnits()[0] ?? '',
        status: nextStatus,
        risk_tier: patient.latest_risk_tier ?? 'UNKNOWN',
        event_type: nextEventType,
      });
    });
  }

  clearSelectedSearchPatient(): void {
    this.selectedSearchPatient.set(null);
    this.searchQuery.set('');
    this.searchResults.set([]);
    this.registerError.set(null);
    this._resetFormToDefaults();
  }

  private _resetFormToDefaults(): void {
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

    const patient = this.selectedSearchPatient();
    const activeEncounterId = this.activeEncounterId();

    if (patient && activeEncounterId) {
      // Update existing active encounter (transfer/discharge/update).
      const payload = {
        status: this.registerForm.value.status,
        unit: this.registerForm.value.unit,
        risk_tier: this.registerForm.value.risk_tier,
        event_type: this.registerForm.value.event_type || null,
      };

      this.encountersApi.updateEncounter(activeEncounterId, payload).subscribe({
        next: (encounter) => {
          this.isRegistering.set(false);
          this.registrationSuccess.set(true);
          this.toast.success(`Encounter updated: ${encounter.id}`);
          this.router.navigate(['/encounters'], { queryParams: { patient: patient.patient_id, name: `${patient.first_name} ${patient.last_name}` } });
        },
        error: (err: { message?: string; status?: number; error?: { detail?: string } }) => {
          this.isRegistering.set(false);
          const detail = err.error?.detail ?? err.message ?? 'Failed to update encounter.';
          this.registerError.set(detail);
          this.toast.error(detail);
        },
      });
      return;
    }

    // Create a new encounter for patients without an active encounter.
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
        this.router.navigate(['/encounters'], { queryParams: { patient: patient?.patient_id, name: patient ? `${patient.first_name} ${patient.last_name}` : '' } });
      },
      error: (err: { message?: string; status?: number; error?: { detail?: string } }) => {
        this.isRegistering.set(false);
        const detail = err.error?.detail ?? err.message ?? 'Failed to register encounter.';
        this.registerError.set(detail);
        this.toast.error(detail);
      },
    });
  }

  goBack(): void {
    this.router.navigate(['/patients']);
  }
}
