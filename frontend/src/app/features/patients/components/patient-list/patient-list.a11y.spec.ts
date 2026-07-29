import { TestBed, ComponentFixture } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { of } from 'rxjs';
import axe from 'axe-core';

import { PatientListComponent } from './patient-list.component';
import { PatientApiService } from '../../services/patient-api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { RiskTier } from '../../../../shared/models';
import { Subject } from 'rxjs';

/** Runs axe-core against the rendered component and asserts zero violations. */
async function assertNoA11yViolations(fixture: ComponentFixture<unknown>): Promise<void> {
  fixture.detectChanges();
  await fixture.whenStable();

  const results = await axe.run(fixture.nativeElement as HTMLElement, {
    runOnly: {
      type: 'tag',
      values: ['wcag2a', 'wcag2aa'],
    },
  });

  if (results.violations.length > 0) {
    const summary = results.violations
      .map(v => `[${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} node(s))`)
      .join('\n');
    fail(`axe-core found ${results.violations.length} WCAG 2.1 AA violation(s):\n${summary}`);
  }
}

const MOCK_PATIENTS = [
  {
    encounter_id: 'ENC-001',
    patient_id: 'PAT-001',
    mrn_masked: '****1234',
    first_name: 'John',
    last_name: 'Smith',
    date_of_birth: '1960-03-15',
    current_unit: '3A',
    room_number: '301A',
    risk_tier: RiskTier.HIGH,
    risk_score: 88,
    admission_date: '2026-07-10',
  },
  {
    encounter_id: 'ENC-002',
    patient_id: 'PAT-002',
    mrn_masked: '****5678',
    first_name: 'Jane',
    last_name: 'Doe',
    date_of_birth: '1975-08-22',
    current_unit: '3A',
    room_number: '302B',
    risk_tier: RiskTier.LOW,
    risk_score: 12,
    admission_date: '2026-07-12',
  },
];

describe('PatientListComponent — Accessibility (WCAG 2.1 AA)', () => {
  let fixture: ComponentFixture<PatientListComponent>;

  async function createFixture(
    overrides: { patients?: typeof MOCK_PATIENTS; loadError?: boolean } = {},
  ) {
    const riskScoreUpdated$ = new Subject();
    await TestBed.configureTestingModule({
      imports: [
        PatientListComponent,
        NoopAnimationsModule,
        RouterTestingModule,
        HttpClientTestingModule,
      ],
      providers: [
        {
          provide: PatientApiService,
          useValue: {
            getPatients: () =>
              overrides.loadError
                ? of(null).pipe(() => { throw new Error('API error'); })
                : of({
                    items: overrides.patients ?? MOCK_PATIENTS,
                    total: (overrides.patients ?? MOCK_PATIENTS).length,
                    page: 1,
                    page_size: 25,
                  }),
          },
        },
        {
          provide: AuthService,
          useValue: { getPatientClaim: () => ['3A', '3B'] },
        },
        {
          provide: SignalRService,
          useValue: { riskScoreUpdated$: riskScoreUpdated$.asObservable() },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PatientListComponent);
    return fixture;
  }

  it('should have no WCAG 2.1 AA violations with patient data loaded', async () => {
    fixture = await createFixture();
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with HIGH risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.HIGH }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with MEDIUM risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.MEDIUM }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with LOW risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.LOW }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations with UNSCORED risk badge visible', async () => {
    fixture = await createFixture({
      patients: [{ ...MOCK_PATIENTS[0], risk_tier: RiskTier.UNSCORED }],
    });
    await assertNoA11yViolations(fixture);
  });

  it('should have no WCAG 2.1 AA violations when patient list is empty', async () => {
    fixture = await createFixture({ patients: [] });
    await assertNoA11yViolations(fixture);
  });
});
