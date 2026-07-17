---
id: TASK-002
title: "SignalR Message Handlers — adt_event_received, task_updated, alert_created, bed_status_changed"
user_story: US-048
epic: EP-009
sprint: 2
layer: Frontend / Core
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TR-003, NFR-006]
---

# TASK-002: SignalR Message Handlers — adt_event_received, task_updated, alert_created, bed_status_changed

> **Story:** US-048 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Core | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

TASK-001 establishes the `SignalRService` with raw Observable streams. This task adds the **handler layer** — Angular services that listen to those streams, transform the payloads into domain state, and expose derived signals/stores that UI components can bind to directly.

This separation of concerns keeps the `SignalRService` infrastructure-focused and keeps business logic (e.g., "only keep the last 20 ADT events", "merge task status into encounter store") in dedicated feature services.

Four handlers are required, one per event type:

| Handler | Listens to | Drives |
|---------|------------|--------|
| `AdtEventHandlerService` | `adtEvent$` | `adtEvents` signal (capped at 20 items) |
| `TaskUpdateHandlerService` | `taskUpdated$` | `taskStatusMap` signal (keyed by `taskId`) |
| `AlertHandlerService` | `alertCreated$` | `activeAlerts` signal (keyed by `alertId`) |
| `BedStatusHandlerService` | `bedStatusChanged$` | `bedStatusMap` signal (keyed by `bedId`) |

All handler services are `providedIn: 'root'` and self-initialise by subscribing in their constructors.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/core/signalr/handlers/adt-event-handler.service.ts` | Service | Maintains signal of last 20 ADT events |
| `src/app/core/signalr/handlers/task-update-handler.service.ts` | Service | Maintains task status map signal |
| `src/app/core/signalr/handlers/alert-handler.service.ts` | Service | Maintains active alerts map signal |
| `src/app/core/signalr/handlers/bed-status-handler.service.ts` | Service | Maintains bed status map signal |
| `src/app/core/signalr/handlers/adt-event-handler.service.spec.ts` | Unit test | ADT handler slice tests |
| `src/app/core/signalr/handlers/task-update-handler.service.spec.ts` | Unit test | Task update handler tests |

**Design references:**
- design.md §3.3 — SignalR Hub groups and message types
- US-048 AC Scenario 1 — ADT event appears in panel within 1 second
- US-048 AC Scenario 2 — Task status badge updates within 1 second
- US-048 DoD — four message handler types required

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | `AdtEventHandlerService` appends new ADT events to the capped signal; dashboard panel reads signal |
| Scenario 2 | `TaskUpdateHandlerService` updates task status in the map; badge component reads the signal |
| Scenario 4 | Server-side group filtering ensures handler only receives relevant unit/role events |

---

## Implementation Steps

### 1. Create `adt-event-handler.service.ts`

```typescript
import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService } from '../signalr.service';
import { AdtEventPayload } from '../signalr.models';

/** Maximum number of ADT events to retain in the live feed (US-048 DoD). */
const MAX_ADT_EVENTS = 20;

/**
 * Listens to `adtEvent$` from SignalRService and maintains a capped, chronologically
 * ordered signal of the last 20 ADT events for the Live ADT Events panel.
 */
@Injectable({ providedIn: 'root' })
export class AdtEventHandlerService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly sub: Subscription;

  // Immutable signal — components read via `adtEvents` computed or directly
  private readonly _adtEvents = signal<AdtEventPayload[]>([]);

  /** Last 20 ADT events, newest first. */
  readonly adtEvents = computed(() => this._adtEvents());

  constructor() {
    // Self-initialise: start listening immediately on service construction
    this.sub = this.signalR.adtEvent$.subscribe((event) => {
      this._adtEvents.update((current) => {
        // Prepend new event; trim to MAX_ADT_EVENTS
        const updated = [event, ...current];
        return updated.length > MAX_ADT_EVENTS
          ? updated.slice(0, MAX_ADT_EVENTS)
          : updated;
      });
    });
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
```

### 2. Create `task-update-handler.service.ts`

```typescript
import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService } from '../signalr.service';
import { TaskUpdatedPayload } from '../signalr.models';

/**
 * Listens to `taskUpdated$` from SignalRService and maintains a map of
 * task statuses keyed by `taskId`. Task status badge components derive their
 * display state from this map.
 */
@Injectable({ providedIn: 'root' })
export class TaskUpdateHandlerService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly sub: Subscription;

  // Map<taskId, TaskUpdatedPayload> — latest state per task
  private readonly _taskStatusMap = signal<Map<string, TaskUpdatedPayload>>(
    new Map(),
  );

  /** Immutable snapshot of the task status map. */
  readonly taskStatusMap = this._taskStatusMap.asReadonly();

  constructor() {
    this.sub = this.signalR.taskUpdated$.subscribe((update) => {
      this._taskStatusMap.update((map) => {
        // Replace the entry — creates a new Map to trigger signal reactivity
        const next = new Map(map);
        next.set(update.taskId, update);
        return next;
      });
    });
  }

  /**
   * Returns the latest status payload for a given task ID.
   * Returns `null` if no update has been received yet for this task.
   */
  getTaskStatus(taskId: string): TaskUpdatedPayload | null {
    return this._taskStatusMap().get(taskId) ?? null;
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
```

### 3. Create `alert-handler.service.ts`

```typescript
import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService } from '../signalr.service';
import { AlertCreatedPayload } from '../signalr.models';

/**
 * Listens to `alertCreated$` and maintains a map of active alerts keyed by alertId.
 * High-severity alerts (HIGH, CRITICAL) are also forwarded to ToastService (TASK-005).
 */
@Injectable({ providedIn: 'root' })
export class AlertHandlerService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly sub: Subscription;

  private readonly _alertsMap = signal<Map<string, AlertCreatedPayload>>(
    new Map(),
  );

  /** All active alerts, newest first. */
  readonly activeAlerts = computed(() =>
    Array.from(this._alertsMap().values()).sort(
      (a, b) =>
        new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    ),
  );

  /** High and critical severity alerts only — used for toast notification filtering. */
  readonly highPriorityAlerts = computed(() =>
    this.activeAlerts().filter(
      (a) => a.severity === 'HIGH' || a.severity === 'CRITICAL',
    ),
  );

  constructor() {
    this.sub = this.signalR.alertCreated$.subscribe((alert) => {
      this._alertsMap.update((map) => {
        const next = new Map(map);
        next.set(alert.alertId, alert);
        return next;
      });
    });
  }

  /** Dismisses an alert from the active map (e.g., after nurse acknowledgement). */
  dismiss(alertId: string): void {
    this._alertsMap.update((map) => {
      const next = new Map(map);
      next.delete(alertId);
      return next;
    });
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
```

### 4. Create `bed-status-handler.service.ts`

```typescript
import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService } from '../signalr.service';
import { BedStatusChangedPayload } from '../signalr.models';

/**
 * Listens to `bedStatusChanged$` and maintains a map of current bed statuses
 * keyed by `bedId`. The Bed Board component (US-049) reads this map directly.
 */
@Injectable({ providedIn: 'root' })
export class BedStatusHandlerService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly sub: Subscription;

  private readonly _bedStatusMap = signal<Map<string, BedStatusChangedPayload>>(
    new Map(),
  );

  readonly bedStatusMap = this._bedStatusMap.asReadonly();

  constructor() {
    this.sub = this.signalR.bedStatusChanged$.subscribe((update) => {
      this._bedStatusMap.update((map) => {
        const next = new Map(map);
        next.set(update.bedId, update);
        return next;
      });
    });
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
```

### 5. Update `src/app/core/signalr/index.ts` barrel

```typescript
// Add handler exports
export { AdtEventHandlerService } from './handlers/adt-event-handler.service';
export { TaskUpdateHandlerService } from './handlers/task-update-handler.service';
export { AlertHandlerService } from './handlers/alert-handler.service';
export { BedStatusHandlerService } from './handlers/bed-status-handler.service';
```

---

## Validation Loop

```bash
# Type-check
npx tsc --noEmit

# Unit tests — handlers only
npx jest src/app/core/signalr/handlers --coverage
```

**Expected outputs:**
- Zero TypeScript errors
- `AdtEventHandlerService`: capped at 20, newest-first order verified
- `TaskUpdateHandlerService`: map updated correctly on duplicate taskId

---

## Definition of Done Checklist

- [ ] `AdtEventHandlerService` caps feed at 20 events; emits newest first
- [ ] `TaskUpdateHandlerService` updates map on each `task_updated` event
- [ ] `AlertHandlerService` separates high-priority alerts for toast routing
- [ ] `BedStatusHandlerService` maintains current bed state map
- [ ] All handlers self-subscribe in constructors; unsubscribe in `ngOnDestroy`
- [ ] Unit tests cover: initial state, first event, duplicate event, overflow (>20)
- [ ] No TypeScript strict-mode errors
````
