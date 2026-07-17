---
id: TASK-004
title: "Integrate SignalR `risk_score_updated` Event for Real-Time Badge Updates in Patient List"
user_story: US-049
epic: EP-009
sprint: 2
layer: Frontend — Real-Time / SignalR Integration
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [FR-071, NFR-006]
---

# TASK-004: Integrate SignalR `risk_score_updated` Event for Real-Time Badge Updates in Patient List

> **Story:** US-049 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend — Real-Time / SignalR Integration | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

When the Follow-up Care Agent updates a patient's risk score, the FastAPI backend broadcasts a `risk_score_updated` SignalR event to the `unit-{unitId}` group (design.md §3.3). `PatientListComponent` must listen to this event and mutate the relevant `PatientSummary` entry in its local signal so that `RiskBadgeComponent` re-renders without a page refresh, within the 1-second SignalR latency SLA (NFR-006).

The SignalR hub connection is managed by the existing `SignalRService` (scaffolded in US-048). This task adds the `risk_score_updated` listener and the patch logic in `PatientListComponent`.

---

## Acceptance Criteria Addressed

| US-049 AC | Requirement |
|---|---|
| **Scenario 3** | `risk_score_updated` event received → badge updates in <1 second without page refresh |

---

## Implementation Steps

### 1. Define `RiskScoreUpdatedEvent` in `patients/models/`

```typescript
// frontend/src/app/features/patients/models/risk-score-updated.event.ts

import { RiskTier } from '../../../shared/models/risk-tier.enum';

/**
 * Payload of the `risk_score_updated` SignalR event emitted by the
 * FastAPI hub when the Follow-up Care Agent recalculates a patient's
 * risk tier.
 */
export interface RiskScoreUpdatedEvent {
  encounter_id: string;
  risk_tier: RiskTier;
  risk_score: number;
  updated_at: string; // ISO 8601
}
```

### 2. Extend `SignalRService` with Typed Event Stream

In `core/signalr/signalr.service.ts` (from US-048), add a typed observable for the `risk_score_updated` event if not already present:

```typescript
// Add to existing SignalRService:
import { RiskScoreUpdatedEvent } from '../../features/patients/models/risk-score-updated.event';

/**
 * Observable stream of risk_score_updated events from the dashboard hub.
 * Consumers subscribe and unsubscribe via their own takeUntil patterns.
 */
readonly riskScoreUpdated$: Observable<RiskScoreUpdatedEvent> =
  new Observable<RiskScoreUpdatedEvent>(observer => {
    this.hubConnection.on('risk_score_updated', (event: RiskScoreUpdatedEvent) =>
      observer.next(event),
    );
  });
```

> **Note:** If `SignalRService` already exposes a generic `on<T>(eventName)` method, use that instead and avoid the above addition to keep `SignalRService` decoupled from feature models.

### 3. Subscribe to `riskScoreUpdated$` in `PatientListComponent`

Add the following to the `ngOnInit()` method of `PatientListComponent` (created in TASK-003), after the existing `combineLatest` subscription:

```typescript
// In PatientListComponent.ngOnInit(), after existing combineLatest subscription:
this.signalRService.riskScoreUpdated$
  .pipe(takeUntil(this.destroy$))
  .subscribe(event => {
    this.patients.update(current =>
      current.map(p =>
        p.encounter_id === event.encounter_id
          ? { ...p, risk_tier: event.risk_tier, risk_score: event.risk_score }
          : p,
      ),
    );
  });
```

Also inject `SignalRService`:

```typescript
private readonly signalRService = inject(SignalRService);
```

### 4. Unit Tests — `patient-list-signalr.spec.ts`

```typescript
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { ComponentFixture } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { PatientListComponent } from './patient-list.component';
import { SignalRService } from '../../../../core/signalr/signalr.service';
import { PatientApiService } from '../services/patient-api.service';
import { AuthService } from '../../../../core/auth/auth.service';
import { RiskTier } from '../../../shared/models/risk-tier.enum';
import { RiskScoreUpdatedEvent } from '../models/risk-score-updated.event';
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
          useValue: { getUnitClaims: () => ['3A'] },
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
```

---

## File Targets

| Action | Path |
|--------|------|
| **Create** | `frontend/src/app/features/patients/models/risk-score-updated.event.ts` |
| **Update** | `frontend/src/app/core/signalr/signalr.service.ts` — add `riskScoreUpdated$` observable |
| **Update** | `frontend/src/app/features/patients/components/patient-list/patient-list.component.ts` — inject `SignalRService`, subscribe to `riskScoreUpdated$` |
| **Create** | `frontend/src/app/features/patients/components/patient-list/patient-list-signalr.spec.ts` |

---

## Definition of Done

- [ ] `RiskScoreUpdatedEvent` interface defined with `encounter_id`, `risk_tier`, `risk_score`, `updated_at`
- [ ] `SignalRService.riskScoreUpdated$` observable added (or generic `on<T>()` used)
- [ ] `PatientListComponent` subscribes to `riskScoreUpdated$` with `takeUntil(destroy$)` — no memory leak
- [ ] Signal `patients` updated immutably via `.update(current => current.map(...))` — no direct mutation
- [ ] Badge updates without triggering a new API call
- [ ] Both SignalR unit tests pass with `fakeAsync`

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Task | `RiskTier` enum |
| TASK-003 | Task | `PatientListComponent` must exist with `patients` signal and `destroy$` |
| US-048 | Story | `SignalRService` with hub connection to `/hubs/dashboard` must be scaffolded |
