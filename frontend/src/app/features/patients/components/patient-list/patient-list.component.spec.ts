import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { of } from 'rxjs';

import { PatientListComponent } from './patient-list.component';
import { PatientApiService } from '../../services/patient-api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { RiskTier } from '../../../../shared/models/risk-tier.enum';

describe('PatientListComponent', () => {
  let fixture: ComponentFixture<PatientListComponent>;
  let component: PatientListComponent;

  beforeEach(async () => {
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
              of({
                items: [
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
                ],
                total: 1,
                page: 1,
                page_size: 25,
              }),
          },
        },
        {
          provide: AuthService,
          useValue: {
            getPatientClaim: () => ['3A'],
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PatientListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should display patient data', () => {
    expect(component.patients().length).toBeGreaterThan(0);
  });
});
