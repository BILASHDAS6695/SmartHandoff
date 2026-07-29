/**
 * DashboardRealtimeNotificationService — bridges SignalR events to UI notifications.
 * Handles REST fallback polls on reconnect and MatSnackBar toast notifications.
 *
 * US-048 TASK-005
 */
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
    this.snackBar.open(
      '🔗 Reconnected to live dashboard',
      'Dismiss',
      SNACK_CONFIG_INFO,
    );

    // REST fallback: fetch events missed during the disconnection window
    const since = this.signalR.lastEventTime;
    if (!since) return; // No events received yet — nothing to backfill

    this.encountersApi.getRecentEvents(since).subscribe({
      next: (response) => {
        // Inject missed events into the ADT handler's signal
        // This ensures the UI remains synchronized after a network outage
        response.events.forEach((event) => {
          // The ADT event handler maintains the 20-event cap
          // so old events are automatically pruned
          this.adtHandler['_adtEvents'].update((current) => {
            const updated = [event, ...current];
            return updated.length > 20 ? updated.slice(0, 20) : updated;
          });
        });
      },
      error: (error) => {
        console.error('REST fallback poll failed:', error);
        // Best-effort — silently fail; user still sees the reconnected toast
      },
    });
  }

  // ---------------------------------------------------------------------------
  // Private — task completion watcher
  // ---------------------------------------------------------------------------

  private watchTaskCompletions(): void {
    // Subscribe to the taskUpdated$ stream and filter for COMPLETED events
    const sub = this.signalR.taskUpdated$
      .pipe(filter((task) => task.newStatus === 'COMPLETED'))
      .subscribe((task) => {
        // Show toast notification with task name (US-048 AC Scenario 2)
        this.snackBar.open(
          `✓ ${task.taskName} completed`,
          'Dismiss',
          SNACK_CONFIG_SUCCESS,
        );
      });

    this.subs.push(sub);
  }

  // ---------------------------------------------------------------------------
  // Private — high-priority alert watcher
  // ---------------------------------------------------------------------------

  private watchHighPriorityAlerts(): void {
    // Subscribe to the alertCreated$ stream and filter for high-priority alerts
    const sub = this.signalR.alertCreated$
      .pipe(
        filter(
          (alert) =>
            alert.severity === 'HIGH' || alert.severity === 'CRITICAL',
        ),
      )
      .subscribe((alert) => {
        // Show toast notification with alert title
        this.snackBar.open(
          `⚠️ ${alert.title}: ${alert.message}`,
          'Dismiss',
          SNACK_CONFIG_ALERT,
        );
      });

    this.subs.push(sub);
  }
}
