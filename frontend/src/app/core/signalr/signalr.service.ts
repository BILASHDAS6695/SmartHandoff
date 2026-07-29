/**
 * SignalRService — manages the WebSocket connection to the FastAPI SignalR hub
 * for real-time ADT events, task updates, alerts, and bed status changes.
 *
 * US-048 requirements:
 *   - HubConnectionBuilder with accessTokenFactory (JWT auth via query param)
 *   - withAutomaticReconnect with exponential backoff [0, 2000, 5000, 10000, 30000]ms
 *   - Exposes 4 typed Observable streams: adtEvent$, taskUpdated$, alertCreated$, bedStatusChanged$
 *   - Maintains connectionState signal for UI indicators
 *   - Tracks lastEventTime for REST fallback polls after reconnect
 *   - Invokes JoinGroups on connect and reconnect for server-side filtering
 *
 * Design: Angular standalone service (providedIn: 'root'); uses inject() API and signals.
 * RxJS Subject bridges SignalR callbacks to Angular Observables.
 */
import { Injectable, OnDestroy, inject, signal } from '@angular/core';
import {
  HubConnection,
  HubConnectionBuilder,
  HubConnectionState,
  LogLevel,
} from '@microsoft/signalr';
import { Subject, Observable } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { environment } from '../../../environments/environment';
import {
  AdtEventPayload,
  AlertCreatedPayload,
  BedStatusChangedPayload,
  JoinGroupsRequest,
  SignalRConnectionState,
  TaskUpdatedPayload,
} from './signalr.models';
import type { RiskScoreUpdatedEvent } from '../../features/patients/models/risk-score-updated.event';

/** Retry intervals for withAutomaticReconnect — exponential backoff as per US-048 Technical Notes. */
const RECONNECT_DELAYS_MS = [0, 2000, 5000, 10000, 30000];

@Injectable({ providedIn: 'root' })
export class SignalRService implements OnDestroy {
  private readonly authService = inject(AuthService);

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
  private readonly _riskScoreUpdated$ = new Subject<RiskScoreUpdatedEvent>();
  private readonly _documentCreated$ = new Subject<{ documentId: string; status: string }>();
  private readonly _alertResolved$ = new Subject<{ alertId: string; status: string }>();

  readonly adtEvent$: Observable<AdtEventPayload> = this._adtEvent$.asObservable();
  readonly taskUpdated$: Observable<TaskUpdatedPayload> =
    this._taskUpdated$.asObservable();
  readonly alertCreated$: Observable<AlertCreatedPayload> =
    this._alertCreated$.asObservable();
  readonly bedStatusChanged$: Observable<BedStatusChangedPayload> =
    this._bedStatusChanged$.asObservable();
  readonly riskScoreUpdated$: Observable<RiskScoreUpdatedEvent> = this._riskScoreUpdated$.asObservable();
  readonly documentCreated$: Observable<{ documentId: string; status: string }> = this._documentCreated$.asObservable();
  readonly alertResolved$: Observable<{ alertId: string; status: string }> = this._alertResolved$.asObservable();

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
    try {
      await this.connection.start();
      // Transition to Connected state after successful start
      this.connectionState.set('Connected');
      // Join groups on initial connection
      await this.joinGroups(joinRequest);
    } catch (error) {
      this.connectionState.set('Disconnected');
      throw error;
    }
  }

  /** Gracefully closes the hub connection. */
  async disconnect(): Promise<void> {
    if (this.connection) {
      try {
        await this.connection.stop();
      } catch (error) {
        console.error('Error stopping SignalR connection:', error);
      }
      this.connectionState.set('Disconnected');
    }
  }

  ngOnDestroy(): void {
    void this.disconnect();
    this._adtEvent$.complete();
    this._taskUpdated$.complete();
    this._alertCreated$.complete();
    this._bedStatusChanged$.complete();
    this._riskScoreUpdated$.complete();
    this._documentCreated$.complete();
    this._alertResolved$.complete();
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private buildConnection(): HubConnection {
    return new HubConnectionBuilder()
      .withUrl(`${environment.apiBaseUrl}/hubs/dashboard`, {
        // JWT in query param — SignalR limitation for WS upgrade handshake.
        // Token is sourced from in-memory store (never localStorage).
        accessTokenFactory: () => this.authService.getToken() ?? '',
      })
      // Exponential backoff: immediate, 2s, 5s, 10s, 30s (US-048 Technical Notes)
      .withAutomaticReconnect(RECONNECT_DELAYS_MS)
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

    this.connection.on('risk_score_updated', (payload: RiskScoreUpdatedEvent) => {
      this._riskScoreUpdated$.next(payload);
    });

    this.connection.on('document_created', (payload: { documentId: string; status: string }) => {
      this._documentCreated$.next(payload);
    });

    this.connection.on('alert_resolved', (payload: { alertId: string; status: string }) => {
      this._alertResolved$.next(payload);
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
  }

  private async joinGroups(request: JoinGroupsRequest): Promise<void> {
    if (this.connection?.state === HubConnectionState.Connected) {
      try {
        await this.connection.invoke('JoinGroups', request);
      } catch (error) {
        console.error('Error joining groups:', error);
      }
    }
  }
}
