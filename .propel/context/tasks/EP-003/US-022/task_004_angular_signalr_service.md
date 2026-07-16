---
id: TASK-004
title: "Implement Angular `SignalRService` with Automatic Reconnect and `task_updated` Event Handling"
user_story: US-022
epic: EP-003
sprint: 2
layer: Frontend
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-16
assignee: AI/ML Engineer
upstream: [TASK-001, TASK-002]
---

# TASK-004: Implement Angular `SignalRService` with Automatic Reconnect and `task_updated` Event Handling

> **Story:** US-022 | **Epic:** EP-003 | **Sprint:** 2 | **Layer:** Frontend | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-16

---

## Context

US-022 DoD requires:

> *"Angular `SignalRService` implemented with `@microsoft/signalr` SDK, automatic reconnect strategy"*

US-022 Technical Notes specify:

> *"`HubConnectionBuilder` with `withUrl(url, {accessTokenFactory: () => jwtService.getToken()})` and `withAutomaticReconnect()`"*

US-022 Scenario 3 requires:

> *"Angular client automatically reconnects within 5 seconds; missed task updates re-fetched via `GET /api/v1/encounters/{id}/tasks`"*

This task creates the Angular `SignalRService` as a singleton `providedIn: 'root'` service in the `core/signalr/` module. It:
1. Calls the negotiate endpoint (TASK-002) to obtain the Azure SignalR hub URL and client token.
2. Establishes a `HubConnection` using the `@microsoft/signalr` SDK.
3. Configures `withAutomaticReconnect` with a custom retry schedule.
4. Exposes a `taskUpdated$` Observable that the `DashboardComponent` subscribes to.
5. On reconnect, triggers a REST fetch of missed tasks via `EncounterTasksApiService`.

Following Angular development standards, the service uses `inject()` over constructor injection, is standalone-compatible, and uses `toSignal`/`signal` where appropriate.

---

## Acceptance Criteria Addressed

| US-022 AC | Requirement |
|---|---|
| **Scenario 1** | `task_updated` event delivered to Angular client; `taskUpdated$` Observable emits the payload |
| **Scenario 3** | Auto-reconnect within 5 seconds; missed updates re-fetched on reconnection |
| **Scenario 4** | `accessTokenFactory` sends JWT with every connection — unauthenticated connections refused by negotiate endpoint (401) |
| **DoD** | `SignalRService` with `@microsoft/signalr`, auto-reconnect, and task update handling |

---

## Implementation Steps

### 1. Install `@microsoft/signalr`

```bash
cd frontend
npm install @microsoft/signalr
```

Add to `package.json` dependencies (version locked to `^8.0.0`):

```json
{
  "dependencies": {
    "@microsoft/signalr": "^8.0.0"
  }
}
```

### 2. File structure

```
frontend/src/app/core/signalr/
├── signalr.service.ts        ← THIS TASK
├── signalr.service.spec.ts   ← THIS TASK
└── index.ts                  ← barrel export
```

```bash
mkdir -p frontend/src/app/core/signalr
touch frontend/src/app/core/signalr/index.ts
```

### 3. Create `frontend/src/app/core/signalr/signalr.service.ts`

```typescript
/**
 * SignalRService — manages the Azure SignalR WebSocket connection for real-time
 * task_updated events on the care team dashboard.
 *
 * US-022 requirements:
 *   - HubConnectionBuilder with accessTokenFactory (Scenario 4 — JWT auth)
 *   - withAutomaticReconnect with custom retry schedule (Scenario 3 — <5s reconnect)
 *   - task_updated event exposes taskUpdated$ Observable (Scenario 1 — <1s latency)
 *   - On reconnect, re-fetches missed tasks (Scenario 3 — no missed updates)
 *
 * Design: Angular standalone service (providedIn: 'root'); uses inject() API.
 * RxJS Subject bridges SignalR callback to Angular Observable.
 */
import { Injectable, OnDestroy, inject } from '@angular/core';
import {
  HubConnection,
  HubConnectionBuilder,
  HubConnectionState,
  LogLevel,
} from '@microsoft/signalr';
import { Subject, Observable, from, EMPTY } from 'rxjs';
import { catchError, switchMap, tap } from 'rxjs/operators';
import { toSignal } from '@angular/core/rxjs-interop';

import { JwtService } from '../auth/jwt.service';
import { EncounterTasksApiService } from '../api/encounter-tasks-api.service';
import { environment } from '../../../environments/environment';

/** Payload received from the SignalR `task_updated` event.
 *  Mirrors TaskUpdatedPayload on the FastAPI backend (US-022 TASK-001). */
export interface TaskUpdatedEvent {
  task_id: string;
  encounter_id: string;
  unit_id: string;
  role_name: string;
  agent_type: string;
  previous_status: string;
  new_status: string;
  updated_at: string;
}

/** Retry intervals for withAutomaticReconnect — targets <5s reconnect (US-022 Scenario 3). */
const RECONNECT_DELAYS_MS = [0, 1000, 2000, 5000, 10000];

@Injectable({ providedIn: 'root' })
export class SignalRService implements OnDestroy {
  private readonly jwtService = inject(JwtService);
  private readonly encounterTasksApi = inject(EncounterTasksApiService);

  private connection: HubConnection | null = null;
  private readonly _taskUpdated$ = new Subject<TaskUpdatedEvent>();
  private currentEncounterId: string | null = null;

  /** Observable of task_updated events. Subscribe in DashboardComponent. */
  readonly taskUpdated$: Observable<TaskUpdatedEvent> = this._taskUpdated$.asObservable();

  /** Initiates the SignalR connection for the given encounter context.
   *
   * Calls the negotiate endpoint (TASK-002) — the accessTokenFactory ensures the
   * JWT is attached to every connection and reconnection attempt.
   *
   * @param encounterId - Active encounter ID; used to re-fetch missed tasks on reconnect.
   */
  async startConnection(encounterId: string): Promise<void> {
    if (this.connection?.state === HubConnectionState.Connected) {
      return;
    }

    this.currentEncounterId = encounterId;

    this.connection = new HubConnectionBuilder()
      .withUrl(`${environment.apiBaseUrl}/api/v1/signalr/negotiate`, {
        // US-022 Technical Notes: accessTokenFactory injects JWT for every connection.
        // The negotiate endpoint (TASK-002) validates this JWT before issuing the
        // Azure SignalR client token.
        accessTokenFactory: () => this.jwtService.getToken() ?? '',
      })
      .withAutomaticReconnect(RECONNECT_DELAYS_MS)
      .configureLogging(environment.production ? LogLevel.Warning : LogLevel.Information)
      .build();

    this._registerEventHandlers();
    this._registerReconnectHandlers();

    await this.connection.start();
  }

  /** Gracefully stops the connection. Call on component destroy or logout. */
  async stopConnection(): Promise<void> {
    if (this.connection) {
      await this.connection.stop();
      this.connection = null;
    }
  }

  ngOnDestroy(): void {
    this.stopConnection().catch(() => {
      // Swallow stop errors on destroy — connection may already be closed.
    });
    this._taskUpdated$.complete();
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private _registerEventHandlers(): void {
    if (!this.connection) return;

    // US-022 Scenario 1: listen for task_updated events from the hub.
    this.connection.on('task_updated', (payload: TaskUpdatedEvent) => {
      this._taskUpdated$.next(payload);
    });
  }

  private _registerReconnectHandlers(): void {
    if (!this.connection) return;

    this.connection.onreconnecting(() => {
      // Dashboard can show a "Reconnecting…" indicator via taskUpdated$ subscribers.
    });

    this.connection.onreconnected(async () => {
      // US-022 Scenario 3: re-fetch missed task updates after reconnection.
      if (this.currentEncounterId) {
        try {
          const tasks = await this.encounterTasksApi
            .getTasksForEncounter(this.currentEncounterId)
            .toPromise();
          if (tasks) {
            // Emit a synthetic task_updated for each task so the dashboard
            // re-renders to the current server state without requiring a full reload.
            tasks.forEach(task => {
              this._taskUpdated$.next({
                task_id: task.id,
                encounter_id: this.currentEncounterId!,
                unit_id: task.unit_id ?? '',
                role_name: task.target_role ?? '',
                agent_type: task.agent_type,
                previous_status: task.status,
                new_status: task.status,
                updated_at: task.completed_time ?? task.start_time,
              });
            });
          }
        } catch {
          // Reconnect re-fetch is best-effort — log only.
        }
      }
    });

    this.connection.onclose(() => {
      // Connection permanently closed (all retry attempts exhausted).
      // Dashboard should surface an actionable "Connection lost — please refresh" banner.
    });
  }
}
```

### 4. Create `frontend/src/app/core/signalr/index.ts`

```typescript
export { SignalRService, TaskUpdatedEvent } from './signalr.service';
```

### 5. Create `frontend/src/app/core/signalr/signalr.service.spec.ts`

```typescript
/**
 * Unit tests for SignalRService.
 *
 * Tests mock @microsoft/signalr HubConnectionBuilder — no live WebSocket calls.
 * Coverage:
 *   - taskUpdated$ emits when task_updated event is triggered on mock connection.
 *   - startConnection is idempotent when already Connected.
 *   - accessTokenFactory calls JwtService.getToken().
 *   - Reconnect handler calls EncounterTasksApiService.getTasksForEncounter().
 */
import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { of } from 'rxjs';
import { HubConnectionState } from '@microsoft/signalr';

import { SignalRService, TaskUpdatedEvent } from './signalr.service';
import { JwtService } from '../auth/jwt.service';
import { EncounterTasksApiService } from '../api/encounter-tasks-api.service';

// --- Mocks ---

const mockJwtService = { getToken: jest.fn(() => 'test-jwt-token') };

const mockEncounterTasksApi = {
  getTasksForEncounter: jest.fn(() => of([])),
};

/** Captures the event handler registered via connection.on('task_updated', handler). */
let capturedTaskUpdatedHandler: ((payload: TaskUpdatedEvent) => void) | null = null;
let capturedReconnectedHandler: (() => void) | null = null;

const mockConnection = {
  state: HubConnectionState.Disconnected,
  start: jest.fn(async () => { mockConnection.state = HubConnectionState.Connected; }),
  stop: jest.fn(async () => { mockConnection.state = HubConnectionState.Disconnected; }),
  on: jest.fn((event: string, handler: (...args: any[]) => void) => {
    if (event === 'task_updated') capturedTaskUpdatedHandler = handler;
  }),
  onreconnecting: jest.fn(),
  onreconnected: jest.fn((handler: () => void) => { capturedReconnectedHandler = handler; }),
  onclose: jest.fn(),
};

jest.mock('@microsoft/signalr', () => ({
  HubConnectionBuilder: jest.fn().mockImplementation(() => ({
    withUrl: jest.fn().mockReturnThis(),
    withAutomaticReconnect: jest.fn().mockReturnThis(),
    configureLogging: jest.fn().mockReturnThis(),
    build: jest.fn(() => mockConnection),
  })),
  HubConnectionState: { Connected: 'Connected', Disconnected: 'Disconnected' },
  LogLevel: { Warning: 1, Information: 2 },
}));

// ---

describe('SignalRService', () => {
  let service: SignalRService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        SignalRService,
        { provide: JwtService, useValue: mockJwtService },
        { provide: EncounterTasksApiService, useValue: mockEncounterTasksApi },
      ],
    });
    service = TestBed.inject(SignalRService);
  });

  afterEach(() => {
    jest.clearAllMocks();
    capturedTaskUpdatedHandler = null;
    capturedReconnectedHandler = null;
    mockConnection.state = HubConnectionState.Disconnected;
  });

  it('should emit on taskUpdated$ when task_updated event is received', async () => {
    await service.startConnection('enc-001');

    const received: TaskUpdatedEvent[] = [];
    service.taskUpdated$.subscribe(e => received.push(e));

    const mockPayload: TaskUpdatedEvent = {
      task_id: 'task-1',
      encounter_id: 'enc-001',
      unit_id: '3A',
      role_name: 'nurse',
      agent_type: 'DOCUMENTATION',
      previous_status: 'IN_PROGRESS',
      new_status: 'COMPLETED',
      updated_at: new Date().toISOString(),
    };

    capturedTaskUpdatedHandler!(mockPayload);

    expect(received).toHaveLength(1);
    expect(received[0].new_status).toBe('COMPLETED');
  });

  it('should not start a second connection when already Connected', async () => {
    mockConnection.state = HubConnectionState.Connected;
    await service.startConnection('enc-001');
    expect(mockConnection.start).not.toHaveBeenCalled();
  });

  it('should call JwtService.getToken for accessTokenFactory', async () => {
    await service.startConnection('enc-001');
    // Verify HubConnectionBuilder was configured with withUrl containing accessTokenFactory
    const { HubConnectionBuilder } = require('@microsoft/signalr');
    const builderInstance = HubConnectionBuilder.mock.results[0].value;
    expect(builderInstance.withUrl).toHaveBeenCalledWith(
      expect.stringContaining('/negotiate'),
      expect.objectContaining({ accessTokenFactory: expect.any(Function) }),
    );
    const { accessTokenFactory } = builderInstance.withUrl.mock.calls[0][1];
    expect(accessTokenFactory()).toBe('test-jwt-token');
  });

  it('should call getTasksForEncounter on reconnect', async () => {
    await service.startConnection('enc-001');
    await capturedReconnectedHandler!();
    expect(mockEncounterTasksApi.getTasksForEncounter).toHaveBeenCalledWith('enc-001');
  });
});
```

### 6. Integrate `SignalRService` into `DashboardComponent`

Add the following subscription in the existing `DashboardComponent` (feature/dashboard):

```typescript
// frontend/src/app/features/dashboard/dashboard.component.ts

import { Component, OnInit, OnDestroy, inject } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService, TaskUpdatedEvent } from '../../core/signalr';

@Component({
  standalone: true,
  // ... existing metadata ...
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly signalR = inject(SignalRService);
  private taskSub?: Subscription;

  // encounterId sourced from route params or dashboard state
  private encounterId = ''; // set from route/state in ngOnInit

  ngOnInit(): void {
    this.signalR.startConnection(this.encounterId);
    this.taskSub = this.signalR.taskUpdated$.subscribe((event: TaskUpdatedEvent) => {
      this._applyTaskUpdate(event);
    });
  }

  ngOnDestroy(): void {
    this.taskSub?.unsubscribe();
    this.signalR.stopConnection();
  }

  private _applyTaskUpdate(event: TaskUpdatedEvent): void {
    // Update local task state — implementation depends on state management approach.
    // Emit to a local signal or store for display in the task list component.
  }
}
```

---

## Validation Loop

Before marking this task complete, verify:

```bash
# Install dependency
cd frontend && npm install @microsoft/signalr

# Unit tests
npx jest src/app/core/signalr/signalr.service.spec.ts --coverage

# Type check
npx tsc --noEmit

# Build check — ensure no bundle size regression >50KB from signalr SDK
npx ng build --configuration=production --stats-json
node -e "
  const stats = require('./dist/stats.json');
  const main = stats.assets.find(a => a.name.includes('main'));
  console.log('Main chunk KB:', Math.round(main.size / 1024));
"
```

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| TASK-001 | Upstream task | Negotiate URL and `task_updated` event name established |
| TASK-002 | Upstream task | `POST /api/v1/signalr/negotiate` endpoint available |
| `@microsoft/signalr` | npm | v8.x — matches Angular 17 zone-free compatibility |
| `JwtService` | Existing | Core auth service — `getToken()` method must exist |
| `EncounterTasksApiService` | Existing / new | `getTasksForEncounter(id)` returns `Observable<AgentTaskResponse[]>` |
