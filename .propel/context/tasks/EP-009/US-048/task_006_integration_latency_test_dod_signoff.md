---
id: TASK-006
title: "Integration Latency Test + DoD Sign-off — US-048 SignalR Validation"
user_story: US-048
epic: EP-009
sprint: 2
layer: QA / Validation
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Integration Latency Test + DoD Sign-off — US-048 SignalR Validation

> **Story:** US-048 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** QA / Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task completes the US-048 Definition of Done by:

1. Implementing the **server-to-client latency integration test** that measures the time between a SignalR message being sent and the DOM reflecting the update, asserting ≤ 1 second (US-048 DoD)
2. Running the full unit test suite and confirming all tasks TASK-001 through TASK-005 pass
3. Completing the DoD sign-off checklist for US-048

The latency test uses `performance.now()` (as specified in the US-048 DoD) and is implemented as a Jest integration test using a fake SignalR hub stub — no real network required.

### Validation scope

| Validation | Tool | Pass Threshold |
|------------|------|---------------|
| TypeScript type safety | `tsc --noEmit` | Zero errors |
| ESLint | `eslint src/**/*.ts` | Zero warnings |
| Unit tests (all US-048 tasks) | Jest | 100% pass; ≥ 80% line coverage |
| SignalR latency integration test | Jest + `performance.now()` | DOM update ≤ 1000 ms |
| WCAG contrast (badges) | jest-axe | Zero violations |
| Bundle size gate | Angular build | No budget violations |

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/core/signalr/signalr-latency.integration.spec.ts` | Integration test | Measures event-to-DOM latency using `performance.now()` |
| `src/app/features/dashboard/components/live-adt-feed/live-adt-feed.accessibility.spec.ts` | Accessibility test | jest-axe WCAG checks on the live feed component |
| `docs/US-048-dod-checklist.md` | DoD record | Completed Definition of Done checklist |

**Design references:**
- design.md §5.1 TR-003 — SignalR push latency <1 second
- US-048 DoD — integration test with `performance.now()`; ≤ 1 second latency SLA

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| All | Full integration and regression coverage for all four acceptance criteria scenarios |

---

## Implementation Steps

### 1. Create `signalr-latency.integration.spec.ts`

```typescript
// src/app/core/signalr/signalr-latency.integration.spec.ts
//
// Integration test: measures server-to-client event-to-DOM latency.
// Uses a fake HubConnection stub to control event timing precisely.
// Asserts that from the moment an event is dispatched to SignalRService
// until Angular change detection reflects the update in the DOM,
// the elapsed time is ≤ 1000 ms (US-048 DoD, TR-003).

import {
  ComponentFixture,
  TestBed,
  fakeAsync,
  tick,
  flush,
} from '@angular/core/testing';
import { Subject } from 'rxjs';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { AdtEventHandlerService } from './handlers/adt-event-handler.service';
import { LiveAdtFeedComponent } from '@features/dashboard/components/live-adt-feed/live-adt-feed.component';
import { SignalRService } from './signalr.service';
import { AdtEventPayload } from './signalr.models';

// ---------------------------------------------------------------------------
// Fake SignalRService — controls event emission without real network
// ---------------------------------------------------------------------------
class FakeSignalRService {
  private readonly _adtEvent$ = new Subject<AdtEventPayload>();
  readonly adtEvent$ = this._adtEvent$.asObservable();
  readonly taskUpdated$ = new Subject().asObservable();
  readonly alertCreated$ = new Subject().asObservable();
  readonly bedStatusChanged$ = new Subject().asObservable();
  readonly connectionState = () => 'Connected' as const;
  readonly lastEventTime: string | null = null;

  /** Test helper — emit an ADT event into the stream */
  emitAdtEvent(payload: AdtEventPayload): void {
    this._adtEvent$.next(payload);
  }
}

const SAMPLE_ADT_EVENT: AdtEventPayload = {
  eventType: 'A01',
  patientUnit: '3A',
  timestamp: new Date().toISOString(),
  encounterId: 'ENC-TEST-001',
  patientDisplayName: 'J. Doe',
};

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------
describe('SignalR Server-to-Client Latency Integration', () => {
  let fixture: ComponentFixture<LiveAdtFeedComponent>;
  let fakeSignalR: FakeSignalRService;

  beforeEach(async () => {
    fakeSignalR = new FakeSignalRService();

    await TestBed.configureTestingModule({
      imports: [LiveAdtFeedComponent, NoopAnimationsModule],
      providers: [
        { provide: SignalRService, useValue: fakeSignalR },
        AdtEventHandlerService,
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LiveAdtFeedComponent);
    fixture.detectChanges();
  });

  it('should reflect ADT event in DOM within 1000 ms of emission (TR-003)', fakeAsync(() => {
    const startTime = performance.now();

    // Emit event from fake hub
    fakeSignalR.emitAdtEvent(SAMPLE_ADT_EVENT);

    // Allow Angular signal propagation and change detection
    tick(0);
    fixture.detectChanges();
    flush();

    const endTime = performance.now();
    const elapsedMs = endTime - startTime;

    // Verify DOM reflects the event
    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    expect(rows.length).toBeGreaterThanOrEqual(1);

    const firstRowText: string = rows[0].textContent ?? '';
    expect(firstRowText).toContain('A01');
    expect(firstRowText).toContain('3A');

    // Assert latency SLA — in test environment should be well under 1 second;
    // this establishes a regression baseline
    expect(elapsedMs).toBeLessThan(1000);
    console.info(`[US-048 Latency] Event-to-DOM elapsed: ${elapsedMs.toFixed(2)} ms`);
  }));

  it('should handle 20 rapid events without dropping any (capacity test)', fakeAsync(() => {
    for (let i = 0; i < 20; i++) {
      fakeSignalR.emitAdtEvent({
        ...SAMPLE_ADT_EVENT,
        encounterId: `ENC-${i.toString().padStart(3, '0')}`,
        timestamp: new Date(Date.now() + i).toISOString(),
      });
    }

    tick(0);
    fixture.detectChanges();
    flush();

    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    // Capped at 20 (MAX_ADT_EVENTS)
    expect(rows.length).toBe(20);
  }));

  it('should cap feed at 20 events when 21 are emitted', fakeAsync(() => {
    for (let i = 0; i < 21; i++) {
      fakeSignalR.emitAdtEvent({
        ...SAMPLE_ADT_EVENT,
        encounterId: `ENC-OVERFLOW-${i}`,
        timestamp: new Date(Date.now() + i).toISOString(),
      });
    }

    tick(0);
    fixture.detectChanges();
    flush();

    const rows = fixture.nativeElement.querySelectorAll('.event-row');
    expect(rows.length).toBe(20);
  }));
});
```

### 2. Create `live-adt-feed.accessibility.spec.ts`

```typescript
// src/app/features/dashboard/components/live-adt-feed/live-adt-feed.accessibility.spec.ts
// WCAG 2.1 AA accessibility tests using jest-axe.

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { axe, toHaveNoViolations } from 'jest-axe';
import { LiveAdtFeedComponent } from './live-adt-feed.component';
import { SignalRService } from '@core/signalr/signalr.service';
import { AdtEventHandlerService } from '@core/signalr/handlers/adt-event-handler.service';
import { signal } from '@angular/core';
import { AdtEventPayload } from '@core/signalr/signalr.models';

expect.extend(toHaveNoViolations);

const SAMPLE_EVENTS: AdtEventPayload[] = [
  {
    eventType: 'A01',
    patientUnit: '3A',
    timestamp: new Date().toISOString(),
    encounterId: 'ENC-AX-001',
    patientDisplayName: 'J. Doe',
  },
];

describe('LiveAdtFeedComponent — Accessibility (WCAG 2.1 AA)', () => {
  let fixture: ComponentFixture<LiveAdtFeedComponent>;

  const fakeSignalR = {
    connectionState: signal('Connected'),
    adtEvent$: { subscribe: jest.fn() },
    taskUpdated$: { subscribe: jest.fn() },
    alertCreated$: { subscribe: jest.fn() },
    bedStatusChanged$: { subscribe: jest.fn() },
    lastEventTime: null,
  };

  const fakeAdtHandler = {
    adtEvents: signal(SAMPLE_EVENTS),
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LiveAdtFeedComponent, NoopAnimationsModule],
      providers: [
        { provide: SignalRService, useValue: fakeSignalR },
        { provide: AdtEventHandlerService, useValue: fakeAdtHandler },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LiveAdtFeedComponent);
    fixture.detectChanges();
  });

  it('should have no WCAG violations when rendering events', async () => {
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });

  it('should have no WCAG violations in empty state', async () => {
    (fakeAdtHandler.adtEvents as ReturnType<typeof signal<AdtEventPayload[]>>).set([]);
    fixture.detectChanges();
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });
});
```

### 3. Create `docs/US-048-dod-checklist.md`

```markdown
# US-048 Definition of Done — Sign-off Checklist

| # | Requirement | Status | Notes |
|---|-------------|--------|-------|
| 1 | Angular `SignalRService` with `HubConnectionBuilder`, group subscriptions, auto-reconnect | ✅ Done | TASK-001 |
| 2 | `withAutomaticReconnect([0, 2000, 5000, 10000, 30000])` configured | ✅ Done | TASK-001 |
| 3 | Group subscriptions: `encounter-*`, `unit-*`, `role-*` via `JoinGroups` | ✅ Done | TASK-001 |
| 4 | SignalR message handlers: `adt_event_received`, `task_updated`, `alert_created`, `bed_status_changed` | ✅ Done | TASK-002 |
| 5 | Live ADT Events panel on `/dashboard` — real-time feed (last 20 events) with virtual scrolling | ✅ Done | TASK-003 |
| 6 | Task status badge component subscribes to `task_updated` for displayed encounter | ✅ Done | TASK-004 |
| 7 | REST fallback on reconnect: `GET /api/v1/encounters/recent-events?since={last_event_time}` | ✅ Done | TASK-005 |
| 8 | `MatSnackBar` toasts for task completion and high-priority alerts | ✅ Done | TASK-005 |
| 9 | Integration test: latency ≤ 1 second measured with `performance.now()` | ✅ Done | TASK-006 |
| 10 | Code reviewed and approved | ⬜ Pending | PR review |

**Reviewer sign-off:** _____________________ **Date:** _________
```

### 4. Run full US-048 test suite

```bash
# Full test run for US-048 tasks
npx jest \
  src/app/core/signalr \
  src/app/features/dashboard/components/live-adt-feed \
  src/app/features/dashboard/services \
  src/app/shared/components/task-status-badge \
  --coverage \
  --coverageThreshold='{"global":{"lines":80}}'

# Type check
npx tsc --noEmit

# ESLint
npx eslint src/app/core/signalr/**/*.ts src/app/features/dashboard/**/*.ts --max-warnings=0

# Bundle size check
npx ng build --configuration=production --stats-json
# Verify main chunk does not exceed 500 KB (TR-002)
```

### 5. Expected test output summary

```
Test Suites: 8 passed, 8 total
Tests:       34 passed, 34 total

Coverage summary (US-048 scope):
  Statements : ≥ 80%
  Branches   : ≥ 75%
  Lines      : ≥ 80%

[US-048 Latency] Event-to-DOM elapsed: ~2.40 ms  ✓ (< 1000 ms SLA)
```

---

## Validation Loop

```bash
# Run everything in one command
npx jest --testPathPattern="signalr|live-adt-feed|task-status-badge|dashboard-realtime" \
  --coverage --verbose

npx tsc --noEmit && echo "✅ TypeScript OK"
npx eslint "src/**/*.ts" --max-warnings=0 && echo "✅ ESLint OK"
```

---

## Definition of Done Checklist

- [ ] Latency integration test passes: `elapsedMs < 1000` asserted with `performance.now()`
- [ ] 20-event capacity test passes; 21st event correctly dropped
- [ ] jest-axe WCAG tests: zero violations for `LiveAdtFeedComponent`
- [ ] All Jest tests pass (`--passWithNoTests` not used)
- [ ] TypeScript: zero errors (`tsc --noEmit`)
- [ ] ESLint: zero warnings
- [ ] `docs/US-048-dod-checklist.md` created and items 1–9 marked Done
- [ ] PR submitted for code review (DoD item 10 resolved post-review)
````
