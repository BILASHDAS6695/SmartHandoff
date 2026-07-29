/**
 * AlertHandlerService — listens to alert_created messages from SignalRService
 * and maintains a map of active alerts.
 *
 * US-048 TASK-002
 */
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

  /**
   * Returns the latest alert payload for a given alert ID.
   * Returns `null` if no alert has been received for this ID.
   */
  getAlert(alertId: string): AlertCreatedPayload | null {
    return this._alertsMap().get(alertId) ?? null;
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
