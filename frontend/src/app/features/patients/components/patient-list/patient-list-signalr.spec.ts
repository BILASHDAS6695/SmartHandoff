import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { ComponentFixture } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { PatientListComponent } from './patient-list.component';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { PatientApiService } from '../../services/patient-api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { RiskTier } from '../../../../shared/models';
import { RiskScoreUpdatedEvent } from '../../models';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { of } from 'rxjs';

describe('PatientListComponent — SignalR integration', () => {
  let fixture: ComponentFixture<PatientListComponent>;
  let component: PatientListComponent;
  let riskScoreUpdated$: Subject<RiskScoreUpdatedEvent>;

  beforeEach(async () => {
    riskScoreUpdated$ = new Subject<RiskScoreUpdatedEvent>();

    await TestBed.configureTestingModule({
      imports: [
        PatientListComponent,
        RouterTestingModule,
        HttpClientTestingModule,
        NoopAnimationsModule,
      ],
      providers: [
        {
          provide: SignalRService,
          useValue: { riskScoreUpdated$: riskScoreUpdated$.asObservable() },
        },
        {
          provide: PatientApiService,
          useValue: {
            getPatients: () =>
              of({
                items: [
                  {
                    encounter_id: 'ENC-001',
                    risk_tier: RiskTier.MEDIUM,
                    risk_score: 42,
                    last_name: 'Smith',
                    first_name: 'John',
                    mrn_masked: '****1234',
                    current_unit: '3A',
                    room_number: '301A',
                    admission_date: '2026-07-10',
                    patient_id: 'PAT-001',
                    date_of_birth: '1960-03-15',
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
          useValue: { getPatientClaim: () => ['3A'] },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(PatientListComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should update risk badge when risk_score_updated event received', fakeAsync(() => {
    // Pre-condition: patient starts as MEDIUM
    expect(component.patients()[0].risk_tier).toBe(RiskTier.MEDIUM);

    // Emit SignalR event
    riskScoreUpdated$.next({
      encounter_id: 'ENC-001',
      risk_tier: RiskTier.HIGH,
      risk_score: 85,
      updated_at: '2026-07-17T10:00:00Z',
    });
    tick();
    fixture.detectChanges();

    // Post-condition: patient risk_tier updated to HIGH
    expect(component.patients()[0].risk_tier).toBe(RiskTier.HIGH);
  }));

  it('should not mutate unrelated patients on risk_score_updated', fakeAsync(() => {
    riskScoreUpdated$.next({
      encounter_id: 'ENC-UNRELATED',
      risk_tier: RiskTier.HIGH,
      risk_score: 90,
      updated_at: '2026-07-17T10:00:00Z',
    });
    tick();

    expect(component.patients()[0].risk_tier).toBe(RiskTier.MEDIUM); // unchanged
  }));
});
