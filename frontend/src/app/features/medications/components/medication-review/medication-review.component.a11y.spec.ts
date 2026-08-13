import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { MedicationReviewComponent } from './medication-review.component';
import { MedicationApiService, MedicationReconciliationResponse, PharmacistAlert } from '../../services/medication-api.service';
import { PatientApiService } from '../../../patients/services/patient-api.service';
import { ToastService } from '../../../../core/notifications/toast.service';
import { of, throwError } from 'rxjs';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { RouterTestingModule } from '@angular/router/testing';
import { ActivatedRoute } from '@angular/router';

expect.extend(toHaveNoViolations);

const MOCK_RECONCILIATION: MedicationReconciliationResponse = {
  encounter_id: 'enc-001',
  total_medications: 2,
  reconciliation_completed_at: null,
  reconciliation_completed_by: null,
  medications: [
    {
      id: '1',
      name: 'Warfarin',
      rxnorm_cui: '11289',
      reconciliation_category: 'CONTINUED',
      pre_admit: true,
      inpatient: true,
      discharge: true,
      flags: [],
      dose: '5.0 mg',
      route: 'oral',
      frequency: 'Daily',
      interaction_severity: 'HIGH',
    },
    {
      id: '2',
      name: 'Aspirin',
      rxnorm_cui: '1191',
      reconciliation_category: 'CONTINUED',
      pre_admit: true,
      inpatient: true,
      discharge: true,
      flags: [],
      dose: '81.0 mg',
      route: 'oral',
      frequency: 'Daily',
      interaction_severity: null,
    },
  ],
};

const MOCK_ALERTS: PharmacistAlert[] = [
  {
    id: 'alert-1',
    encounter_id: 'enc-001',
    alert_type: 'PHARMACIST_ALERT',
    severity: 'HIGH',
    status: 'ACTIVE',
    drug_class: null,
    drug_name: null,
    drug_pair: ['Warfarin', 'Aspirin'],
    interaction_description: 'Increased bleeding risk.',
    source: 'SYSTEM',
    sla_breached: false,
    resolved_by_user_id: null,
    resolved_at: null,
    resolution_type: null,
    created_at: new Date().toISOString(),
  },
];

const mockMedicationApi = {
  generateReconciliation: jest.fn(() => of(MOCK_RECONCILIATION)),
  getEncounterAlerts: jest.fn(() => of(MOCK_ALERTS)),
};

const mockPatientApi = {
  getPatientByEncounter: jest.fn(() => of({ first_name: 'Test', last_name: 'Patient' })),
};

const mockToast = {
  info: jest.fn(),
  success: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
};

const mockActivatedRoute = {
  snapshot: { paramMap: { get: jest.fn(() => 'enc-001') } },
};

describe('MedicationReviewComponent — a11y', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MedicationReviewComponent, RouterTestingModule],
      providers: [
        provideAnimationsAsync(),
        { provide: MedicationApiService, useValue: mockMedicationApi },
        { provide: PatientApiService, useValue: mockPatientApi },
        { provide: ToastService, useValue: mockToast },
        { provide: ActivatedRoute, useValue: mockActivatedRoute },
      ],
    }).compileComponents();
  });

  it('should have no WCAG 2.1 AA violations', async () => {
    const fixture = TestBed.createComponent(MedicationReviewComponent);
    fixture.componentRef.setInput('patientId', 'p-001');
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });

  it('should render error state accessibly on API failure', async () => {
    const failingApi = {
      generateReconciliation: jest.fn(() => throwError(() => new Error('API error'))),
      getEncounterAlerts: jest.fn(() => of([])),
    };

    await TestBed.overrideProvider(MedicationApiService, { useValue: failingApi }).compileComponents();
    const fixture = TestBed.createComponent(MedicationReviewComponent);
    fixture.componentRef.setInput('patientId', 'p-001');
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });
});
