---
id: TASK-005
title: "REST Fallback on Reconnect + MatSnackBar Toast Notifications"
user_story: US-048
epic: EP-009
sprint: 2
layer: Frontend / Core + Feature
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, NFR-006, TR-001]
---

# TASK-005: REST Fallback on Reconnect + MatSnackBar Toast Notifications

> **Story:** US-048 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Core + Feature | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements two closely related concerns that both trigger on SignalR lifecycle events:

**1. REST Fallback Poll (Scenario 3):** When the SignalR connection is restored after a network interruption, the `onreconnected` callback must fetch missed events via `GET /api/v1/encounters/recent-events?since={last_event_time}`. This prevents a data gap in the Live ADT Events panel during a connectivity outage. `SignalRService.lastEventTime` (set in TASK-001) provides the `since` parameter.

**2. Toast Notifications (Scenario 2):** When a `task_updated` event arrives with `newStatus === 'COMPLETED'`, a `MatSnackBar` toast must appear with the task name. When a `CRITICAL` or `HIGH` alert arrives, a toast must appear with the alert title. A "Reconnected" toast must appear when the SignalR connection is restored.

These two concerns are implemented as a single `DashboardRealtimeNotificationService` that observes `SignalRService` state changes and `TaskUpdateHandlerService` / `AlertHandlerService` event streams.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/features/dashboard/services/dashboard-realtime-notification.service.ts` | Service | REST fallback + toast orchestration on SignalR events |
| `src/app/core/api/encounters-api.service.ts` | Service | Typed HTTP client for `GET /api/v1/encounters/recent-events` |
| `src/app/features/dashboard/services/dashboard-realtime-notification.service.spec.ts` | Unit test | Reconnect fallback, toast on task completion, toast on alert |

**Design references:**
- design.md §3.3 — REST fallback: `GET /api/v1/encounters/recent-events?since={last_event_time}`
- US-048 AC Scenario 3 — Reconnected toast; missed events fetched via REST
- US-048 AC Scenario 2 — toast with task name on task completion
- US-048 DoD — `MatSnackBar` for agent task completion and high-priority alerts

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 2 | `MatSnackBar` toast fires on `task_updated` with `newStatus === 'COMPLETED'` |
| Scenario 3 | REST poll fires on `connectionState` transition to `Connected` after `Reconnecting`; "Reconnected" toast shown |

---

## Implementation Steps

### 1. Create `encounters-api.service.ts`

```typescript
// src/app/core/api/encounters-api.service.ts
// Typed HTTP client for the encounters REST API.
// Only the `getRecentEvents` method is required for US-048; additional methods will be added in US-049.

import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '@env/environment';
import { AdtEventPayload } from '@core/signalr/signalr.models';

export interface RecentEventsResponse {
  events: AdtEventPayload[];
  /** ISO-8601 timestamp of the most recent event in this response */
  latestEventTime: string;
}

@Injectable({ providedIn: 'root' })
export class EncountersApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/api/v1/encounters`;

  /**
   * Fetches ADT events that occurred after the given ISO-8601 timestamp.
   * Used as a REST fallback after SignalR reconnects to backfill missed events.
   *
   * @param since - ISO-8601 timestamp of the last event received before disconnect
   */
  getRecentEvents(since: string): Observable<RecentEventsResponse> {
    const params = new HttpParams().set('since', since);
    return this.http.get<RecentEventsResponse>(`${this.baseUrl}/recent-events`, {
      params,
    });
  }
}
```

### 2. Create `dashboard-realtime-notification.service.ts`

```typescript
// src/app/features/dashboard/services/dashboard-realtime-notification.service.ts
//
// Orchestrates:
//   - REST fallback poll on SignalR reconnect
//   - MatSnackBar toasts for task completions, high-priority alerts, reconnect events

import { Injectable, OnDestroy, effect, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarConfig } from '@angular/material/snack-bar';
import { Subscription } from 'rxjs';
import { filter } from 'rxjs/operators';
import { SignalRService } from '@core/signalr/signalr.service';
import { TaskUpdateHandlerService } from '@core/signalr/handlers/task-update-handler.service';
import { AlertHandlerService } from '@core/signalr/handlers/alert-handler.service';
import { AdtEventHandlerService } from '@core/signalr/handlers/adt-event-handler.service';
import { EncountersApiService } from '@core/api/encounters-api.service';

/** Default snackbar duration in milliseconds */
const SNACK_DURATION_MS = 4000;

const SNACK_CONFIG_SUCCESS: MatSnackBarConfig = {
  duration: SNACK_DURATION_MS,
  panelClass: ['snack--success'],
  horizontalPosition: 'end',
  verticalPosition: 'top',
};

const SNACK_CONFIG_ALERT: MatSnackBarConfig = {
  duration: 6000,
  panelClass: ['snack--alert'],
  horizontalPosition: 'end',
  verticalPosition: 'top',
};

const SNACK_CONFIG_INFO: MatSnackBarConfig = {
  duration: SNACK_DURATION_MS,
  panelClass: ['snack--info'],
  horizontalPosition: 'end',
  verticalPosition: 'top',
};

/**
 * Feature-scoped service that bridges SignalR events to UI notifications.
 *
 * Lifecycle: instantiate once in `DashboardShellComponent` — the service
 * self-registers subscriptions in its constructor and tears them down via ngOnDestroy.
 * Do NOT provide in root — it should only run when the dashboard feature is active.
 */
@Injectable()
export class DashboardRealtimeNotificationService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly taskHandler = inject(TaskUpdateHandlerService);
  private readonly alertHandler = inject(AlertHandlerService);
  private readonly adtHandler = inject(AdtEventHandlerService);
  private readonly encountersApi = inject(EncountersApiService);
  private readonly snackBar = inject(MatSnackBar);

  private readonly subs: Subscription[] = [];

  // Track whether the previous connection state was 'Reconnecting'
  // so we only trigger the fallback on a genuine reconnect (not initial connect)
  private _wasReconnecting = false;

  constructor() {
    this.watchConnectionState();
    this.watchTaskCompletions();
    this.watchHighPriorityAlerts();
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  // ---------------------------------------------------------------------------
  // Private — connection state watcher
  // ---------------------------------------------------------------------------

  private watchConnectionState(): void {
    // Use Angular effect() to reactively respond to the connectionState signal
    effect(() => {
      const state = this.signalR.connectionState();

      if (state === 'Reconnecting') {
        this._wasReconnecting = true;
      }

      if (state === 'Connected' && this._wasReconnecting) {
        this._wasReconnecting = false;
        this.handleReconnect();
      }
    });
  }

  private handleReconnect(): void {
    // Show "Reconnected" toast (US-048 AC Scenario 3)
    this.snackBar.open('🔗 Reconnected to live dashboard', 'Dismiss', SNACK_CONFIG_INFO);

    // REST fallback: fetch events missed during the disconnection window
    const since = this.signalR.lastEventTime;
    if (!since) return; // No events received yet — nothing to backfill

    const sub = this.encountersApi
      .getRecentEvents(since)
      .subscribe({
        next: (response) => {
          // Replay missed events through the ADT handler's internal subject.
          // We access the handler's subject indirectly via the SignalRService to
          // maintain the single event pipeline. In practice, inject SignalRService
          // and call a dedicated backfill method (added in TASK-001 extension).
          response.events.forEach((event) => {
            // Trigger the adtEvent$ pipeline — SignalRService exposes a
            // `replayEvent()` method for exactly this purpose.
            // (See TASK-001 signalr.service.ts — add this method alongside registerHandlers)
            (this.signalR as unknown as { _adtEvent$: { next: (e: unknown) => void } })
              ._adtEvent$.next(event);
          });
        },
        error: () => {
          this.snackBar.open(
            'Could not fetch missed events. Please refresh.',
            'Dismiss',
            { ...SNACK_CONFIG_ALERT, duration: 8000 },
          );
        },
      });

    this.subs.push(sub);
  }

  // ---------------------------------------------------------------------------
  // Private — task completion toast (US-048 AC Scenario 2)
  // ---------------------------------------------------------------------------

  private watchTaskCompletions(): void {
    const sub = this.signalR.taskUpdated$
      .pipe(filter((update) => update.newStatus === 'COMPLETED'))
      .subscribe((update) => {
        this.snackBar.open(
          `✅ ${update.taskName} completed`,
          'View',
          SNACK_CONFIG_SUCCESS,
        );
      });

    this.subs.push(sub);
  }

  // ---------------------------------------------------------------------------
  // Private — high-priority alert toast
  // ---------------------------------------------------------------------------

  private watchHighPriorityAlerts(): void {
    const sub = this.signalR.alertCreated$
      .pipe(
        filter(
          (alert) =>
            alert.severity === 'HIGH' || alert.severity === 'CRITICAL',
        ),
      )
      .subscribe((alert) => {
        this.snackBar.open(
          `🚨 ${alert.title} — Unit ${alert.patientUnit}`,
          'Dismiss',
          SNACK_CONFIG_ALERT,
        );
      });

    this.subs.push(sub);
  }
}
```

### 3. Register service in `DashboardShellComponent`

In `src/app/features/dashboard/shell/shell.component.ts`:

```typescript
// Add to providers array of the shell component
// (DashboardRealtimeNotificationService is NOT provided in root)
@Component({
  selector: 'app-dashboard-shell',
  standalone: true,
  providers: [DashboardRealtimeNotificationService],
  // ...
})
export class DashboardShellComponent {
  // Inject to activate lifecycle — the service self-subscribes in constructor
  private readonly _notifications = inject(DashboardRealtimeNotificationService);
}
```

### 4. Add global snackbar panel styles to `styles.scss`

```scss
// Global snackbar panel class overrides — added to src/styles.scss

.snack--success .mdc-snackbar__surface {
  background-color: #1b5e20;
  color: #ffffff;
}

.snack--alert .mdc-snackbar__surface {
  background-color: #b71c1c;
  color: #ffffff;
}

.snack--info .mdc-snackbar__surface {
  background-color: #0d47a1;
  color: #ffffff;
}
```

---

## Validation Loop

```bash
npx tsc --noEmit
npx jest src/app/features/dashboard/services --coverage

# Manual verification:
# 1. Open /dashboard in browser
# 2. Disconnect network for 3 seconds, reconnect
# 3. Verify "Reconnected" toast appears within 5 seconds
# 4. Verify REST GET /api/v1/encounters/recent-events?since=... fires in Network tab
```

---

## Definition of Done Checklist

- [ ] `EncountersApiService.getRecentEvents(since)` calls correct endpoint with `since` query param
- [ ] `DashboardRealtimeNotificationService` provided at `DashboardShellComponent` level (not root)
- [ ] "Reconnected" toast appears on `connectionState` transition from `Reconnecting` → `Connected`
- [ ] REST fallback fired on reconnect; replays missed ADT events into the live feed
- [ ] `MatSnackBar` toast fires for every `task_updated` event where `newStatus === 'COMPLETED'`
- [ ] `MatSnackBar` toast fires for `alert_created` events with `severity === HIGH | CRITICAL`
- [ ] Toast fires only once per event (no duplicate subscriptions)
- [ ] Unit tests: reconnect toast, fallback REST call, task completion toast, high-priority alert toast
- [ ] No TypeScript strict-mode errors
````
