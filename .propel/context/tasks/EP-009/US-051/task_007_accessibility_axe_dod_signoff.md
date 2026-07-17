---
id: TASK-007
title: "axe-core WCAG 2.1 AA Accessibility Tests and Definition of Done Sign-off"
user_story: US-051
epic: EP-009
sprint: 2
layer: Frontend — Testing + QA
estimate: 1h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [NFR-034, US-049]
---

# TASK-007: axe-core WCAG 2.1 AA Accessibility Tests and Definition of Done Sign-off

> **Story:** US-051 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Testing + QA | **Est:** 1 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

All four components delivered by US-051 must pass WCAG 2.1 AA accessibility checks via `axe-core` before the story can be closed. The two primary screens are `/patients/{id}/medications` (Medication Review + Alert Resolution Modal) and `/dashboard` (Document Queue + Agent Progress Card). Tests run inside Angular `TestBed` with `axe-core` integrated via `jest-axe` or `@axe-core/angular`, following the pattern established in US-049 (TASK-005).

This task also performs the final Definition of Done verification across all checklist items for US-051.

---

## Acceptance Criteria Addressed

| US-051 AC | Requirement |
|---|---|
| **DoD** | `axe-core` WCAG 2.1 AA test on both screens |
| **DoD** | Code reviewed and approved |

---

## Implementation Steps

### 1. Accessibility Test — `MedicationReviewComponent`

**`medication-review.component.a11y.spec.ts`**

```typescript
import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { MedicationReviewComponent } from './medication-review.component';
import { MedicationApiService } from '../../services/medication-api.service';
import { of } from 'rxjs';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

expect.extend(toHaveNoViolations);

const MOCK_RECONCILIATION = {
  encounterId: 'enc-001',
  preAdmit: [
    { id: '1', drugName: 'Warfarin', dose: '5mg', frequency: 'Daily', interactionSeverity: 'HIGH', alertId: 'alert-1' },
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
```

### 2. Accessibility Test — `AlertResolutionModalComponent`

**`alert-resolution-modal.component.a11y.spec.ts`**

```typescript
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
  severity: 'HIGH',
  status: 'OPEN',
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
```

### 3. Accessibility Test — `DocumentQueueComponent`

**`document-queue.component.a11y.spec.ts`**

```typescript
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
    documentType: 'DISCHARGE_SUMMARY',
    generatedAt: '2026-07-17T10:00:00Z',
    status: 'PENDING_REVIEW',
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
            reviewDocument: () => of({ ...MOCK_DOCS[0], status: 'APPROVED' }),
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
```

### 4. Accessibility Test — `AgentProgressCardComponent`

**`agent-progress-card.component.a11y.spec.ts`**

```typescript
import { TestBed } from '@angular/core/testing';
import { axe, toHaveNoViolations } from 'jest-axe';
import { AgentProgressCardComponent } from './agent-progress-card.component';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

expect.extend(toHaveNoViolations);

const MOCK_TASKS = [
  { agentType: 'TRANSITION_COORDINATOR', status: 'COMPLETED', updatedAt: '2026-07-17T09:00:00Z', slaBreach: false, slaDeadline: '2026-07-17T09:30:00Z' },
  { agentType: 'DOCUMENTATION', status: 'IN_PROGRESS', updatedAt: '2026-07-17T09:10:00Z', slaBreach: false, slaDeadline: '2026-07-17T09:40:00Z' },
  { agentType: 'MEDICATION_RECONCILIATION', status: 'PENDING', updatedAt: '2026-07-17T09:05:00Z', slaBreach: false, slaDeadline: '2026-07-17T09:35:00Z' },
  { agentType: 'BED_MANAGEMENT', status: 'FAILED', updatedAt: '2026-07-17T08:55:00Z', slaBreach: true, slaDeadline: '2026-07-17T09:00:00Z' },
  { agentType: 'FOLLOW_UP_CARE', status: 'PENDING', updatedAt: '2026-07-17T09:05:00Z', slaBreach: false, slaDeadline: '2026-07-17T10:00:00Z' },
];

describe('AgentProgressCardComponent — a11y', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AgentProgressCardComponent],
      providers: [provideAnimationsAsync()],
    }).compileComponents();
  });

  it('should have no WCAG 2.1 AA violations', async () => {
    const fixture = TestBed.createComponent(AgentProgressCardComponent);
    fixture.componentRef.setInput('tasks', MOCK_TASKS);
    fixture.detectChanges();
    await fixture.whenStable();

    const results = await axe(fixture.nativeElement, {
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa'] },
    });
    expect(results).toHaveNoViolations();
  });

  it('should render SLA breach row with red alarm icon for BED_MANAGEMENT', () => {
    const fixture = TestBed.createComponent(AgentProgressCardComponent);
    fixture.componentRef.setInput('tasks', MOCK_TASKS);
    fixture.detectChanges();

    const slaIcons = fixture.nativeElement.querySelectorAll('.agent-progress__sla-icon');
    expect(slaIcons.length).toBe(1);
  });
});
```

### 5. Install `jest-axe` (if not already present)

```bash
npm install --save-dev jest-axe @types/jest-axe
```

---

## Definition of Done Verification

| DoD Item | Owner | Verified By |
|---|---|---|
| `MedicationReviewComponent`: three-column `MatTable` with severity badges | TASK-001 | Code review + axe spec |
| `AlertResolutionModalComponent`: `MatDialog` with `MatRadioGroup` and note `MatTextarea` | TASK-003 | Code review + axe spec |
| `DocumentQueueComponent`: `MatList` of `PENDING_REVIEW` docs with approve/reject | TASK-004 | Code review + axe spec |
| `AgentProgressCardComponent`: reusable status icon card for all 5 agent types | TASK-005 | Code review + axe spec |
| Role-based rendering: medication panel pharmacist/physician only; document queue physician only | TASK-006 | Manual test + unit test |
| Toast on alert resolution: "Alert resolved — medication review complete" | TASK-003 | Manual test |
| Error recovery: each panel has error state + retry button | TASK-001, 003, 004 | Unit test |
| `axe-core` WCAG 2.1 AA test on both screens | **This task** | axe spec pass |
| Code reviewed and approved | — | PR review by tech lead |

---

## Files to Create / Modify

| Action | File |
|--------|------|
| CREATE | `src/app/features/medications/components/medication-review/medication-review.component.a11y.spec.ts` |
| CREATE | `src/app/features/medications/components/alert-resolution-modal/alert-resolution-modal.component.a11y.spec.ts` |
| CREATE | `src/app/features/documents/components/document-queue/document-queue.component.a11y.spec.ts` |
| CREATE | `src/app/shared/components/agent-progress-card/agent-progress-card.component.a11y.spec.ts` |

---

## Validation Checklist

- [ ] `jest-axe` installed and configured in `jest.config.ts`
- [ ] All four axe specs pass with zero WCAG 2.1 AA violations
- [ ] Error state axe spec passes for `MedicationReviewComponent`
- [ ] Empty state axe spec passes for `DocumentQueueComponent`
- [ ] SLA breach icon count assertion passes for `AgentProgressCardComponent`
- [ ] All US-051 DoD items checked off and verified

---

## Dependencies

| Dependency | Notes |
|---|---|
| TASK-001 through TASK-006 (this story) | All components must be implemented before axe tests run |
| US-049 (TASK-005) | Pattern established — replicate `jest-axe` setup |
