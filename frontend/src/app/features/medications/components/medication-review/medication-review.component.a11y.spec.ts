import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { MedicationReviewComponent } from './medication-review.component';
import { MedicationApiService } from '../../services/medication-api.service';
import { of, throwError } from 'rxjs';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

expect.extend(toHaveNoViolations);

const MOCK_RECONCILIATION = {
  encounterId: 'enc-001',
  preAdmit: [
    { id: '1', drugName: 'Warfarin', dose: '5mg', frequency: 'Daily', interactionSeverity: 'HIGH' as const, alertId: 'alert-1' },
  ],
  inpatient: [
    { id: '2', drugName: 'Aspirin', dose: '100mg', frequency: 'Daily', interactionSeverity: null, alertId: null },
  ],
  discharge: [],
};

describe('MedicationReviewComponent — a11y', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [MedicationReviewComponent],
      providers: [
        provideAnimationsAsync(),
        {
          provide: MedicationApiService,
          useValue: { getReconciliation: () => of(MOCK_RECONCILIATION) },
        },
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
    const apiSpy = jasmine.createSpyObj('MedicationApiService', ['getReconciliation']);
    apiSpy.getReconciliation.and.returnValue(throwError(() => new Error('API error')));

    await TestBed.overrideProvider(MedicationApiService, { useValue: apiSpy }).compileComponents();
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
