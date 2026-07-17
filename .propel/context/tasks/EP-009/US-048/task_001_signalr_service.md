---
id: TASK-001
title: "SignalRService — HubConnectionBuilder, Group Subscriptions, Auto-Reconnect"
user_story: US-048
epic: EP-009
sprint: 2
layer: Frontend / Core
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-047, TR-003, NFR-006, SEC-001]
---

# TASK-001: SignalRService — HubConnectionBuilder, Group Subscriptions, Auto-Reconnect

> **Story:** US-048 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Core | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task creates the singleton `SignalRService` that acts as the single point of entry for all real-time communication between the Angular PWA and the FastAPI SignalR hub at `/hubs/dashboard`. All dashboard feature components consume this service — they must never construct their own `HubConnection` instances.

The service handles the full connection lifecycle:
- Build the connection with JWT token in query param (SignalR WebSocket limitation — Bearer header not supported on initial WS upgrade handshake)
- Join role-scoped and unit-scoped groups on connect via `JoinGroups` hub method
- Auto-reconnect with exponential backoff delays `[0, 2000, 5000, 10000, 30000]` ms
- Expose a connection state signal (`connectionState`) for UI indicators
- Expose typed Observable streams per event type — consumed by TASK-002 handlers

**Important:** The JWT must be sourced from `AUTH_SERVICE.getAccessToken()` (injection token from US-047 TASK-003), never from `localStorage` directly, to honour the in-memory token storage security rule from design.md §8.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/core/signalr/signalr.service.ts` | Service | Singleton SignalR hub connection manager |
| `src/app/core/signalr/signalr.models.ts` | Models | TypeScript interfaces for all SignalR event payloads |
| `src/app/core/signalr/signalr.service.spec.ts` | Unit test | Connection lifecycle, group subscription, reconnect tests |
| `src/app/core/signalr/index.ts` | Barrel | Public API exports for `core/signalr` |

**Design references:**
- design.md §3.3 — SignalR Hub: `/hubs/dashboard`, groups: `encounter-{id}`, `unit-{unitId}`, `role-{roleName}`
- design.md §4.1 — `@microsoft/signalr` v7.x
- design.md §5.1 TR-003 — SignalR push latency <1 second
- US-048 Technical Notes — connection URL, `JoinGroups` invocation, reconnect delays

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Service establishes connection and dispatches `adt_event_received` messages to subscribed listeners |
| Scenario 3 | `withAutomaticReconnect([0, 2000, 5000, 10000, 30000])` handles reconnect; REST fallback triggered on `onreconnected` |
| Scenario 4 | `JoinGroups` invocation on connect limits server-side fanout to unit and role groups |

---

## Implementation Steps

### 1. Install `@microsoft/signalr`

```bash
# From the Angular workspace root
npm install @microsoft/signalr@7
```

### 2. Create `src/app/core/signalr/signalr.models.ts`

```typescript
// Typed payload interfaces for all SignalR hub messages dispatched by the FastAPI backend.
// Each interface maps 1:1 to a server-sent event type name.

export interface AdtEventPayload {
  /** HL7 event type code: A01, A02, A03, A08, etc. */
  eventType: string;
  /** Patient unit identifier, e.g. "3A" */
  patientUnit: string;
  /** ISO-8601 timestamp of the event */
  timestamp: string;
  /** EHR encounter identifier */
  encounterId: string;
  /** Human-readable patient name (masked per HIPAA display rules) */
  patientDisplayName: string;
}

export interface TaskUpdatedPayload {
  /** Agent task unique identifier */
  taskId: string;
  encounterId: string;
  /** Task type label, e.g. "Documentation Agent" */
  taskName: string;
  /** Previous task status */
  previousStatus: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  /** New task status */
  newStatus: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  /** ISO-8601 completion timestamp (present only when newStatus === 'COMPLETED') */
  completedAt?: string;
}

export interface AlertCreatedPayload {
  alertId: string;
  encounterId: string;
  patientUnit: string;
  /** Alert severity level */
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  title: string;
  message: string;
  timestamp: string;
}

export interface BedStatusChangedPayload {
  bedId: string;
  patientUnit: string;
  /** New bed status */
  status: 'AVAILABLE' | 'OCCUPIED' | 'CLEANING' | 'MAINTENANCE';
  encounterId?: string;
  timestamp: string;
}

/** Union of all inbound SignalR event payloads */
export type SignalREventPayload =
  | AdtEventPayload
  | TaskUpdatedPayload
  | AlertCreatedPayload
  | BedStatusChangedPayload;

/** Connection state values mirroring @microsoft/signalr HubConnectionState */
export type SignalRConnectionState =
  | 'Disconnected'
  | 'Connecting'
  | 'Connected'
  | 'Disconnecting'
  | 'Reconnecting';

/** Payload sent to the server's JoinGroups hub method on connect */
export interface JoinGroupsRequest {
  /** Unit IDs the current user belongs to, e.g. ["3A", "3B"] */
  units: string[];
  /** Role names, e.g. ["NURSE", "CHARGE_NURSE"] */
  roles: string[];
}
```

### 3. Create `src/app/core/signalr/signalr.service.ts`

```typescript
import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import {
  HubConnection,
  HubConnectionBuilder,
  HubConnectionState,
  LogLevel,
} from '@microsoft/signalr';
import { Subject } from 'rxjs';
import { environment } from '@env/environment';
import { AUTH_SERVICE } from '@core/auth/auth.service.token';
import {
  AdtEventPayload,
  AlertCreatedPayload,
  BedStatusChangedPayload,
  JoinGroupsRequest,
  SignalRConnectionState,
  TaskUpdatedPayload,
} from './signalr.models';

/**
 * Singleton service managing the Angular ↔ FastAPI SignalR hub connection.
 *
 * Usage:
 *   Inject `SignalRService` and subscribe to the typed event Observables.
 *   Call `connect(joinRequest)` once after the user authenticates.
 *   Call `disconnect()` on application teardown or logout.
 *
 * Architecture note (design.md §3.3):
 *   Connection URL: `{API_BASE_URL}/hubs/dashboard?access_token={jwt}`
 *   JWT is passed as a query param — the WebSocket upgrade handshake does not
 *   support the `Authorization` header on all browsers.
 */
@Injectable({ providedIn: 'root' })
export class SignalRService implements OnDestroy {
  private readonly authService = inject(AUTH_SERVICE);

  // ---------------------------------------------------------------------------
  // Connection state — writable signal for template binding
  // ---------------------------------------------------------------------------
  readonly connectionState = signal<SignalRConnectionState>('Disconnected');

  // ---------------------------------------------------------------------------
  // Typed event streams — components subscribe to these Observables
  // ---------------------------------------------------------------------------
  private readonly _adtEvent$ = new Subject<AdtEventPayload>();
  private readonly _taskUpdated$ = new Subject<TaskUpdatedPayload>();
  private readonly _alertCreated$ = new Subject<AlertCreatedPayload>();
  private readonly _bedStatusChanged$ = new Subject<BedStatusChangedPayload>();

  readonly adtEvent$ = this._adtEvent$.asObservable();
  readonly taskUpdated$ = this._taskUpdated$.asObservable();
  readonly alertCreated$ = this._alertCreated$.asObservable();
  readonly bedStatusChanged$ = this._bedStatusChanged$.asObservable();

  // Emits the timestamp string of the last successfully received event.
  // Used by the REST fallback poll to fetch missed events after reconnect.
  private _lastEventTime: string | null = null;
  get lastEventTime(): string | null {
    return this._lastEventTime;
  }

  private connection: HubConnection | null = null;

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /**
   * Builds and starts the SignalR hub connection.
   * Invokes `JoinGroups` on the hub immediately after connection is established.
   *
   * @param joinRequest - Units and roles for server-side group subscription
   */
  async connect(joinRequest: JoinGroupsRequest): Promise<void> {
    if (this.connection?.state === HubConnectionState.Connected) {
      return; // Already connected — idempotent
    }

    this.connection = this.buildConnection();
    this.registerHandlers();
    this.registerLifecycleHooks(joinRequest);

    this.connectionState.set('Connecting');
    await this.connection.start();
    // Lifecycle hooks will transition state to 'Connected'
  }

  /** Gracefully closes the hub connection. */
  async disconnect(): Promise<void> {
    if (this.connection) {
      await this.connection.stop();
      this.connectionState.set('Disconnected');
    }
  }

  ngOnDestroy(): void {
    void this.disconnect();
    this._adtEvent$.complete();
    this._taskUpdated$.complete();
    this._alertCreated$.complete();
    this._bedStatusChanged$.complete();
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private buildConnection(): HubConnection {
    return new HubConnectionBuilder()
      .withUrl(`${environment.apiBaseUrl}/hubs/dashboard`, {
        // JWT in query param — SignalR limitation for WS upgrade handshake.
        // Token is sourced from in-memory store (never localStorage).
        accessTokenFactory: () => this.authService.getAccessToken() ?? '',
      })
      // Exponential backoff: immediate, 2s, 5s, 10s, 30s (US-048 Technical Notes)
      .withAutomaticReconnect([0, 2000, 5000, 10000, 30000])
      // Use binary MessagePack protocol to reduce payload size (TR-003)
      .withHubProtocol(new (require('@microsoft/signalr-protocol-msgpack').MessagePackHubProtocol)())
      .configureLogging(
        environment.production ? LogLevel.Warning : LogLevel.Information,
      )
      .build();
  }

  private registerHandlers(): void {
    if (!this.connection) return;

    this.connection.on('adt_event_received', (payload: AdtEventPayload) => {
      this._lastEventTime = payload.timestamp;
      this._adtEvent$.next(payload);
    });

    this.connection.on('task_updated', (payload: TaskUpdatedPayload) => {
      if (payload.completedAt) {
        this._lastEventTime = payload.completedAt;
      }
      this._taskUpdated$.next(payload);
    });

    this.connection.on('alert_created', (payload: AlertCreatedPayload) => {
      this._lastEventTime = payload.timestamp;
      this._alertCreated$.next(payload);
    });

    this.connection.on('bed_status_changed', (payload: BedStatusChangedPayload) => {
      this._lastEventTime = payload.timestamp;
      this._bedStatusChanged$.next(payload);
    });
  }

  private registerLifecycleHooks(joinRequest: JoinGroupsRequest): void {
    if (!this.connection) return;

    this.connection.onclose(() => {
      this.connectionState.set('Disconnected');
    });

    this.connection.onreconnecting(() => {
      this.connectionState.set('Reconnecting');
    });

    this.connection.onreconnected(async () => {
      this.connectionState.set('Connected');
      // Re-join groups after reconnect — server clears group memberships on disconnect
      await this.joinGroups(joinRequest);
    });

    // Set Connected state after initial start() resolves
    // (onreconnected only fires on auto-reconnect cycles, not initial connect)
    this.connection.onclose(null as never); // clear default
    const originalStart = this.connection.start.bind(this.connection);
    // Wrap start to set Connected after resolution
    this.connection.start = async () => {
      await originalStart();
      this.connectionState.set('Connected');
      await this.joinGroups(joinRequest);
    };
  }

  private async joinGroups(request: JoinGroupsRequest): Promise<void> {
    if (this.connection?.state === HubConnectionState.Connected) {
      await this.connection.invoke('JoinGroups', request);
    }
  }
}
```

### 4. Create `src/app/core/signalr/index.ts`

```typescript
// Barrel export for the core/signalr module.
export { SignalRService } from './signalr.service';
export type {
  AdtEventPayload,
  TaskUpdatedPayload,
  AlertCreatedPayload,
  BedStatusChangedPayload,
  JoinGroupsRequest,
  SignalRConnectionState,
} from './signalr.models';
```

### 5. Register `@microsoft/signalr-protocol-msgpack` (optional — production optimisation)

```bash
# MessagePack binary protocol reduces payload size for high-frequency ADT events (TR-003)
npm install @microsoft/signalr-protocol-msgpack@7
```

> **Note:** If MessagePack is not available in the environment, remove `.withHubProtocol(...)` from `buildConnection()`. The service falls back to JSON protocol transparently.

---

## Validation Loop

After implementation, run:

```bash
# Type-check
npx tsc --noEmit

# Unit tests
npx jest src/app/core/signalr --coverage

# Verify @microsoft/signalr is in package.json dependencies (not devDependencies)
cat package.json | grep signalr
```

**Expected outputs:**
- Zero TypeScript errors
- `SignalRService` tests: ≥ 90% line coverage
- `@microsoft/signalr` listed under `dependencies`

---

## Definition of Done Checklist

- [ ] `SignalRService` injectable, `providedIn: 'root'`
- [ ] JWT sourced via `AUTH_SERVICE` injection token — never from `localStorage`
- [ ] `withAutomaticReconnect([0, 2000, 5000, 10000, 30000])` configured
- [ ] All 4 event Observables exposed (`adtEvent$`, `taskUpdated$`, `alertCreated$`, `bedStatusChanged$`)
- [ ] `JoinGroups` invoked on initial connect and on each reconnect
- [ ] `connectionState` signal reflects current hub state
- [ ] `lastEventTime` updated on every inbound event
- [ ] Unit tests pass with ≥ 90% coverage
- [ ] No TypeScript strict-mode errors
````
