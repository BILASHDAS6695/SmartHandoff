# TASK-002: SignalR `bed_status_changed` Handler — Real-Time Cell State Updates

> **Story:** US-050 | **Effort:** 6 hours | **Layer:** Frontend — Real-Time
> **Status:** Draft | **Date:** 2026-07-17

---

## Objective

Create a `BedRealtimeService` that subscribes to the SignalR `bed_status_changed` event and patches the `BedBoardComponent` Signal state so the affected bed cell updates colour and status text within 1 second of message receipt — without a full page refresh (SC2).

---

## Context

US-048 delivers the shared `SignalRService` that manages the hub connection lifecycle (`/hubs/dashboard`). This task consumes that service and wires it to `BedBoardComponent.updateBedStatus()` exposed in TASK-001. The SignalR event is emitted by the Bed Management Agent backend after each ADT event (FR-041, TR-003 <1s latency).

**Upstream Dependencies:**
- TASK-001: `BedBoardComponent.updateBedStatus()` method and `BedUpdateEvent` interface
- US-048: `SignalRService` with `on(event, handler)` and `off(event)` API

---

## Scope

### In Scope

1. **`BedRealtimeService`** — subscribes to `bed_status_changed`, transforms payload to `BedUpdateEvent`, delegates to `BedBoardComponent`
2. **Integration inside `BedBoardComponent`** — inject service, start/stop subscription on `ngOnInit` / `ngOnDestroy`
3. **Connection group join** — request `unit-{unitId}` group via SignalR hub to scope updates to visible units

### Out of Scope

- SignalR hub server implementation (US-048)
- Unit filter logic (TASK-004)
- Unit tests (TASK-005)

---

## Acceptance Criteria

### AC1: Service subscribes to `bed_status_changed`
**Given** `BedRealtimeService.start()` is called
**When** the SignalR hub emits `bed_status_changed` with `{ bedId: "3A-02", status: "VACANT", patientName: null, predictedDischargeTime: null }`
**Then** `BedBoardComponent.updateBedStatus("3A-02", { status: "VACANT", ... })` is invoked within the same event loop tick

### AC2: Bed cell visual update within 1 second
**Given** the bed board is displayed with bed `3A-02` OCCUPIED (blue)
**When** a `bed_status_changed` event arrives with `status: "DIRTY"`
**Then** the bed cell `[ngClass]` switches from `bed-status--occupied` to `bed-status--dirty` without a page refresh; update occurs within 1 second of SignalR message receipt (TR-003)

### AC3: Subscription cleaned up on component destroy
**Given** the nurse navigates away from the bed board
**When** `BedBoardComponent.ngOnDestroy()` is called
**Then** `BedRealtimeService.stop()` unregisters the `bed_status_changed` handler and no memory leaks occur

### AC4: Unknown bedId events are silently ignored
**Given** a `bed_status_changed` event arrives for `bedId: "UNKNOWN-99"`
**When** `updateBedStatus` is called
**Then** the `beds` signal is unchanged (the `map` produces no mutations), and no console error is thrown

---

## Implementation Details

### File: `src/app/features/beds/services/bed-realtime.service.ts`

```typescript
import { Injectable, inject } from '@angular/core';
import { SignalRService } from '@core/signalr/signalr.service';
import { BedUpdateEvent } from '../models/bed.model';

/**
 * Subscribes to the SignalR bed_status_changed event and delegates
 * cell state updates to the BedBoardComponent via callback.
 */
@Injectable({ providedIn: 'root' })
export class BedRealtimeService {
  private readonly signalR = inject(SignalRService);
  private updateCallback: ((event: BedUpdateEvent) => void) | null = null;

  /**
   * Registers the update callback and attaches the SignalR listener.
   * Call once from BedBoardComponent.ngOnInit().
   */
  start(onUpdate: (event: BedUpdateEvent) => void): void {
    this.updateCallback = onUpdate;
    this.signalR.on<BedUpdateEvent>('bed_status_changed', event => {
      this.updateCallback?.(event);
    });
  }

  /** Removes the SignalR listener. Call from BedBoardComponent.ngOnDestroy(). */
  stop(): void {
    this.signalR.off('bed_status_changed');
    this.updateCallback = null;
  }
}
```

### Modification: `src/app/features/beds/components/bed-board/bed-board.component.ts`

Add to existing `BedBoardComponent` (from TASK-001):

```typescript
// Additional imports
import { OnDestroy } from '@angular/core';
import { BedRealtimeService } from '../../services/bed-realtime.service';
import { BedUpdateEvent } from '../../models/bed.model';

// Inject in class body
private readonly bedRealtime = inject(BedRealtimeService);

// In ngOnInit(), after getBeds() subscription:
this.bedRealtime.start((event: BedUpdateEvent) => {
  this.updateBedStatus(event.bedId, {
    status: event.status,
    patientName: event.patientName,
    predictedDischargeTime: event.predictedDischargeTime,
  });
});

// Add ngOnDestroy():
ngOnDestroy(): void {
  this.bedRealtime.stop();
}
```

---

## SignalR Event Contract

The backend (Bed Management Agent) must emit the following payload on the `/hubs/dashboard` hub:

```json
{
  "event": "bed_status_changed",
  "payload": {
    "bedId": "3A-02",
    "status": "VACANT",
    "patientName": null,
    "predictedDischargeTime": null
  }
}
```

`BedUpdateEvent` interface (defined in TASK-001 `bed.model.ts`) maps directly to this payload.

---

## Files Created

| File | Action |
|------|--------|
| `src/app/features/beds/services/bed-realtime.service.ts` | **Create** |

## Files Modified

| File | Change |
|------|--------|
| `src/app/features/beds/components/bed-board/bed-board.component.ts` | Inject `BedRealtimeService`; add SignalR start in `ngOnInit`; add `ngOnDestroy` teardown |

---

## Validation Checklist

- [ ] Open browser devtools → Network → WS tab; confirm `bed_status_changed` message received on mock backend
- [ ] Manually trigger event via SignalR test client; confirm bed cell updates colour without page reload
- [ ] Navigate away from bed board route; confirm no additional `bed_status_changed` handlers remain (inspect `signalR._handlers`)
- [ ] Inject `Subject<BedUpdateEvent>` spy in unit test; emit event; assert `beds` Signal updated correctly
