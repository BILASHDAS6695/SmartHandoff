# TASK-005: Unit Tests — BedBoard, BedDetailPanel, Filter, and SignalR Handler

> **Story:** US-050 | **Effort:** 6 hours | **Layer:** Frontend — Testing
> **Status:** Draft | **Date:** 2026-07-17

---

## Objective

Write Jasmine/Karma unit tests covering all acceptance criteria from TASK-001 through TASK-004. Coverage target: ≥ 80% for all files in `src/app/features/beds/` and `src/app/shared/pipes/mask-name.pipe.ts`.

---

## Context

Tests are written after the implementation tasks are merged to maximise fixture realism. The Angular Signals-based architecture allows synchronous signal updates in tests via `TestBed` — no `fakeAsync` needed for state mutation. SignalR integration is tested via a `Subject<BedUpdateEvent>` stub injected in place of the real `SignalRService`.

**Upstream Dependencies:**
- TASK-001: `BedBoardComponent`, `BedCellComponent`, `BedBoardService`, `MaskNamePipe`, `BedDto`
- TASK-002: `BedRealtimeService`, `BedUpdateEvent`
- TASK-003: `BedDetailPanelComponent`, `AuthService.hasRole()`
- TASK-004: `selectedUnit`, `filteredBeds`, `onUnitFilterChange()`, `ariaLabel`

---

## Scope

### Test Files and Coverage

| File | Test File | Cases |
|------|-----------|-------|
| `mask-name.pipe.ts` | `mask-name.pipe.spec.ts` | 7 |
| `bed-board.component.ts` | `bed-board.component.spec.ts` | 12 |
| `bed-realtime.service.ts` | `bed-realtime.service.spec.ts` | 5 |
| `bed-detail-panel.component.ts` | `bed-detail-panel.component.spec.ts` | 8 |
| `bed-board.component.ts` (filter) | (within `bed-board.component.spec.ts`) | 5 |

**Total:** 37 test cases

---

## Test Cases

### `mask-name.pipe.spec.ts` — 7 cases

| # | Input | Expected Output | Notes |
|---|-------|-----------------|-------|
| 1 | `"John Doe"` | `"J.D."` | Standard two-word name |
| 2 | `"Mary Jane Watson"` | `"M.J.W."` | Three-word name |
| 3 | `"Madonna"` | `"M."` | Single name |
| 4 | `null` | `"—"` | Null guard |
| 5 | `""` | `"—"` | Empty string guard |
| 6 | `"  John  Doe  "` | `"J.D."` | Excess whitespace trimmed |
| 7 | `"jean-luc picard"` | `"J.P."` | Lowercase initials uppercased |

### `bed-board.component.spec.ts` — 17 cases (beds API + filter)

**API Integration (12 cases):**

| # | Scenario | Assertion |
|---|----------|-----------|
| 1 | `getBeds()` returns 3 beds | `beds()` signal has length 3 |
| 2 | Loading state before API resolves | `loading()` is `true`; skeleton cells present |
| 3 | Loading state after API resolves | `loading()` is `false`; skeleton cells absent |
| 4 | API error response | `error()` signal set; error message rendered |
| 5 | Bed with VACANT status | Cell has `bed-status--vacant` class |
| 6 | Bed with OCCUPIED status | Cell has `bed-status--occupied` class |
| 7 | Bed with DIRTY status | Cell has `bed-status--dirty` class |
| 8 | Bed with MAINTENANCE status | Cell has `bed-status--maintenance` class |
| 9 | Bed with RESERVED status | Cell has `bed-status--reserved` class |
| 10 | `predictedDischargeTime` present | Formatted time rendered in cell |
| 11 | `predictedDischargeTime` null | `"—"` rendered in cell |
| 12 | `updateBedStatus("3A-02", {status: "VACANT"})` called | `beds()` signal entry for `3A-02` has `status: "VACANT"` |

**Unit Filter (5 cases):**

| # | Scenario | Assertion |
|---|----------|-----------|
| 13 | Default load, no sessionStorage | `selectedUnit()` is `"ALL"`; all beds in `filteredBeds()` |
| 14 | `onUnitFilterChange("ICU")` called | `filteredBeds()` contains only `unit === "ICU"` beds |
| 15 | `sessionStorage` has `"3A"` on init | `selectedUnit()` initialises to `"3A"` |
| 16 | `onUnitFilterChange("ALL")` called | `filteredBeds()` equals `beds()` |
| 17 | No beds match selected unit | `filteredBeds()` is empty; empty state message rendered |

### `bed-realtime.service.spec.ts` — 5 cases

| # | Scenario | Assertion |
|---|----------|-----------|
| 1 | `start()` registers `bed_status_changed` on `SignalRService` | `signalR.on` called with `"bed_status_changed"` |
| 2 | Event emitted via `Subject` stub | Callback invoked with correct `BedUpdateEvent` payload |
| 3 | `updateBedStatus` called on callback | `BedBoardComponent.updateBedStatus` spy invoked |
| 4 | `stop()` unregisters handler | `signalR.off` called with `"bed_status_changed"` |
| 5 | `stop()` nulls callback | Subsequent event emission does not invoke callback |

### `bed-detail-panel.component.spec.ts` — 8 cases

| # | Scenario | Assertion |
|---|----------|-----------|
| 1 | `bed` input is `null` | Panel does not have `bed-detail-panel--open` class |
| 2 | `bed` input is a valid `BedDto` | Panel has `bed-detail-panel--open` class |
| 3 | `AuthService.hasRole` returns `true` | Full `"John Doe"` name rendered |
| 4 | `AuthService.hasRole` returns `false` | `"J.D."` initials rendered |
| 5 | OCCUPIED bed, `riskTier: "HIGH"` | `risk-chip--high` class present |
| 6 | VACANT bed | `"Assign Bed"` button rendered and enabled |
| 7 | Non-VACANT bed | `"Assign Bed"` button absent from DOM |
| 8 | Escape key pressed | `closed` EventEmitter emits; `bed` set to `null` |

---

## Implementation Details

### File: `src/app/shared/pipes/mask-name.pipe.spec.ts`

```typescript
import { MaskNamePipe } from './mask-name.pipe';

describe('MaskNamePipe', () => {
  let pipe: MaskNamePipe;
  beforeEach(() => { pipe = new MaskNamePipe(); });

  it('masks two-word name to initials', () => {
    expect(pipe.transform('John Doe')).toBe('J.D.');
  });

  it('masks three-word name', () => {
    expect(pipe.transform('Mary Jane Watson')).toBe('M.J.W.');
  });

  it('handles single name', () => {
    expect(pipe.transform('Madonna')).toBe('M.');
  });

  it('returns dash for null', () => {
    expect(pipe.transform(null)).toBe('—');
  });

  it('returns dash for empty string', () => {
    expect(pipe.transform('')).toBe('—');
  });

  it('trims excess whitespace', () => {
    expect(pipe.transform('  John  Doe  ')).toBe('J.D.');
  });

  it('uppercases initials from lowercase input', () => {
    expect(pipe.transform('jean-luc picard')).toBe('J.P.');
  });
});
```

### File: `src/app/features/beds/spec/bed-board.component.spec.ts` (partial)

```typescript
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { BedBoardComponent } from '../components/bed-board/bed-board.component';
import { BedBoardService } from '../services/bed-board.service';
import { BedRealtimeService } from '../services/bed-realtime.service';
import { BedDto } from '../models/bed.model';

const MOCK_BEDS: BedDto[] = [
  { bedId: '3A-01', unit: '3A', status: 'VACANT',      patientName: null,       predictedDischargeTime: null,                   assignedNurse: null, riskTier: null },
  { bedId: '3A-02', unit: '3A', status: 'OCCUPIED',    patientName: 'John Doe', predictedDischargeTime: '2026-07-17T15:00:00Z', assignedNurse: 'N. Smith', riskTier: 'HIGH' },
  { bedId: 'ICU-1', unit: 'ICU', status: 'MAINTENANCE', patientName: null,       predictedDischargeTime: null,                   assignedNurse: null, riskTier: null },
];

describe('BedBoardComponent', () => {
  let bedServiceSpy: jasmine.SpyObj<BedBoardService>;

  beforeEach(() => {
    bedServiceSpy = jasmine.createSpyObj('BedBoardService', ['getBeds']);
    bedServiceSpy.getBeds.and.returnValue(of(MOCK_BEDS));

    TestBed.configureTestingModule({
      imports: [BedBoardComponent],
      providers: [
        { provide: BedBoardService, useValue: bedServiceSpy },
        { provide: BedRealtimeService, useValue: { start: jasmine.createSpy(), stop: jasmine.createSpy() } },
      ],
    });
  });

  it('loads beds into signal on init', () => {
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.beds().length).toBe(3);
  });

  it('shows skeleton during loading', () => {
    bedServiceSpy.getBeds.and.returnValue(new Subject<BedDto[]>());
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.loading()).toBeTrue();
    const skeletons = fixture.nativeElement.querySelectorAll('.bed-cell--skeleton');
    expect(skeletons.length).toBe(12);
  });

  it('sets error signal on API failure', () => {
    bedServiceSpy.getBeds.and.returnValue(throwError(() => new Error('Network error')));
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.error()).toBeTruthy();
  });

  it('updateBedStatus patches the matching bed', () => {
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    fixture.componentInstance.updateBedStatus('3A-02', { status: 'VACANT' });
    const updated = fixture.componentInstance.beds().find(b => b.bedId === '3A-02');
    expect(updated?.status).toBe('VACANT');
  });

  it('updateBedStatus ignores unknown bedId', () => {
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    const before = JSON.stringify(fixture.componentInstance.beds());
    fixture.componentInstance.updateBedStatus('UNKNOWN-99', { status: 'DIRTY' });
    expect(JSON.stringify(fixture.componentInstance.beds())).toBe(before);
  });

  it('filters to ICU unit', () => {
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    fixture.componentInstance.onUnitFilterChange('ICU');
    expect(fixture.componentInstance.filteredBeds().every(b => b.unit === 'ICU')).toBeTrue();
  });

  it('restores unit filter from sessionStorage', () => {
    sessionStorage.setItem('bedboard_unit_filter', '3A');
    const fixture = TestBed.createComponent(BedBoardComponent);
    fixture.detectChanges();
    expect(fixture.componentInstance.selectedUnit()).toBe('3A');
    sessionStorage.removeItem('bedboard_unit_filter');
  });
});
```

### File: `src/app/features/beds/spec/bed-realtime.service.spec.ts` (partial)

```typescript
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';
import { BedRealtimeService } from '../services/bed-realtime.service';
import { SignalRService } from '@core/signalr/signalr.service';
import { BedUpdateEvent } from '../models/bed.model';

describe('BedRealtimeService', () => {
  let service: BedRealtimeService;
  let signalRSpy: jasmine.SpyObj<SignalRService>;

  beforeEach(() => {
    signalRSpy = jasmine.createSpyObj('SignalRService', ['on', 'off']);
    TestBed.configureTestingModule({
      providers: [
        BedRealtimeService,
        { provide: SignalRService, useValue: signalRSpy },
      ],
    });
    service = TestBed.inject(BedRealtimeService);
  });

  it('registers bed_status_changed handler on start', () => {
    service.start(() => {});
    expect(signalRSpy.on).toHaveBeenCalledWith('bed_status_changed', jasmine.any(Function));
  });

  it('invokes callback when SignalR emits event', () => {
    let captured: BedUpdateEvent | undefined;
    signalRSpy.on.and.callFake((_event: string, handler: (e: BedUpdateEvent) => void) => {
      handler({ bedId: '3A-02', status: 'VACANT', patientName: null, predictedDischargeTime: null });
    });
    service.start(ev => { captured = ev; });
    expect(captured?.bedId).toBe('3A-02');
    expect(captured?.status).toBe('VACANT');
  });

  it('unregisters handler on stop', () => {
    service.start(() => {});
    service.stop();
    expect(signalRSpy.off).toHaveBeenCalledWith('bed_status_changed');
  });
});
```

---

## Files Created

| File | Action |
|------|--------|
| `src/app/shared/pipes/mask-name.pipe.spec.ts` | **Create** |
| `src/app/features/beds/spec/bed-board.component.spec.ts` | **Create** |
| `src/app/features/beds/spec/bed-realtime.service.spec.ts` | **Create** |
| `src/app/features/beds/spec/bed-detail-panel.component.spec.ts` | **Create** |

---

## Validation Checklist

- [ ] `ng test --include="**/beds/**" --code-coverage` passes with ≥ 80% statement coverage
- [ ] `ng test --include="**/mask-name.pipe.spec.ts"` — all 7 cases pass
- [ ] All 17 `BedBoardComponent` cases pass (zero flaky tests; no `tick()` dependencies for Signal mutations)
- [ ] All 5 `BedRealtimeService` cases pass
- [ ] All 8 `BedDetailPanelComponent` cases pass
- [ ] No `console.error` output during test run
