import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { AlertResolutionModalComponent } from './alert-resolution-modal.component';
import { InteractionAlertApiService } from '../../services/interaction-alert-api.service';
import { of } from 'rxjs';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

expect.extend(toHaveNoViolations);

const MOCK_ALERT = {
  alertId: 'alert-1',
  encounterId: 'enc-001',
  drug1Name: 'Warfarin',
  drug2Name: 'Aspirin',
  descriptionExcerpt: 'Co-administration increases bleeding risk.',
  descriptionFull: 'Co-administration increases bleeding risk significantly due to additive anticoagulant effect.',
  severity: 'HIGH' as const,
  status: 'OPEN' as const,
};

describe('AlertResolutionModalComponent — a11y', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AlertResolutionModalComponent],
      providers: [
        provideAnimationsAsync(),
        { provide: MAT_DIALOG_DATA, useValue: { alertId: 'alert-1' } },
        { provide: MatDialogRef, useValue: { close: jasmine.createSpy() } },
        {
          provide: InteractionAlertApiService,
          useValue: { getAlert: () => of(MOCK_ALERT), resolveAlert: () => of(MOCK_ALERT) },
        },
      ],
    }).compileComponents();
  });

  it('should have no WCAG 2.1 AA violations on open', async () => {
    const fixture = TestBed.createComponent(AlertResolutionModalComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });
});
