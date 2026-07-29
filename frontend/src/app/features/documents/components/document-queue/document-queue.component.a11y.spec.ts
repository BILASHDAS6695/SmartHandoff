import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { DocumentQueueComponent } from './document-queue.component';
import { DocumentApiService } from '../../services/document-api.service';
import { DocumentQueueStore } from '../../store/document-queue.store';
import { of } from 'rxjs';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

expect.extend(toHaveNoViolations);

const MOCK_DOCS = [
  {
    documentId: 'doc-1',
    encounterId: 'enc-001',
    patientName: 'Jane Smith',
    documentType: 'DISCHARGE_SUMMARY' as const,
    generatedAt: '2026-07-17T10:00:00Z',
    status: 'PENDING_REVIEW' as const,
    contentExcerpt: 'Patient discharged in stable condition…',
  },
];

describe('DocumentQueueComponent — a11y', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DocumentQueueComponent],
      providers: [
        provideAnimationsAsync(),
        DocumentQueueStore,
        {
          provide: DocumentApiService,
          useValue: {
            getPendingReviewQueue: () => of(MOCK_DOCS),
            reviewDocument: () => of({ ...MOCK_DOCS[0], status: 'APPROVED' as const }),
          },
        },
      ],
    }).compileComponents();
  });

  it('should have no WCAG 2.1 AA violations with documents', async () => {
    const fixture = TestBed.createComponent(DocumentQueueComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });

  it('should have no WCAG 2.1 AA violations in empty state', async () => {
    await TestBed.overrideProvider(DocumentApiService, {
      useValue: { getPendingReviewQueue: () => of([]) },
    }).compileComponents();
    const fixture = TestBed.createComponent(DocumentQueueComponent);
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });
});
