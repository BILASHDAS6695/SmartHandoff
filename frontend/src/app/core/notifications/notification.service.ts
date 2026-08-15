/**
 * NotificationService — manages in-app notifications for the header bell dropdown.
 *
 * Responsibilities:
 *   - Maintains a reactive list of AppNotification items.
 *   - Provides imperative add/dismiss/mark-read/clear methods.
 *   - Subscribes to SignalR event streams and auto-generates notifications
 *     for task completions, alerts, and ADT events.
 *
 * US-048 / UXR-021
 */
import { Injectable, OnDestroy, computed, effect, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { v4 as uuidv4 } from 'uuid';

import { SignalRService } from '../signalr/signalr.service';
import { AppNotification } from '../models';

@Injectable({ providedIn: 'root' })
export class NotificationService implements OnDestroy {
  private readonly signalR = inject(SignalRService);

  /** Notifications are generated dynamically from SignalR events and client workflows. */
  private readonly _notifications = signal<AppNotification[]>([]);
  private readonly subs: Subscription[] = [];

  /** All notifications, newest first. */
  readonly notifications = computed(() =>
    [...this._notifications()].sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
    ),
  );

  /** Unread notification count shown on the bell badge. */
  readonly unreadCount = computed(
    () => this._notifications().filter((n) => !n.read).length,
  );

  constructor() {
    this.watchTaskUpdates();
    this.watchAlerts();
    this.watchAdtEvents();
    this.watchBedSuggestions();
    this.watchBoardingAlerts();
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  /**
   * Add a new notification.
   * @param notification Partial notification; id and timestamp are auto-populated.
   * @returns The generated notification id, or the existing id if a notification
   *          with the same key already exists.
   */
  add(notification: Omit<AppNotification, 'id' | 'timestamp' | 'read'> & Partial<Pick<AppNotification, 'id' | 'read'>>): string {
    if (notification.key) {
      const existing = this._notifications().find((n) => n.key === notification.key);
      if (existing) {
        return existing.id;
      }
    }
    const next: AppNotification = {
      id: notification.id ?? uuidv4(),
      read: notification.read ?? false,
      timestamp: new Date().toISOString(),
      ...notification,
    };
    this._notifications.update((current) => [next, ...current]);
    return next.id;
  }

  /** Mark a single notification as read. */
  markAsRead(id: string): void {
    this._notifications.update((current) =>
      current.map((n) => (n.id === id ? { ...n, read: true } : n)),
    );
  }

  /** Mark every notification as read and return the previous unread count. */
  markAllAsRead(): number {
    const count = this.unreadCount();
    this._notifications.update((current) => current.map((n) => ({ ...n, read: true })));
    return count;
  }

  /** Dismiss (remove) a single notification. */
  dismiss(id: string): void {
    this._notifications.update((current) => current.filter((n) => n.id !== id));
  }

  /** Clear every notification. */
  clear(): void {
    this._notifications.set([]);
  }

  // ---------------------------------------------------------------------------
  // Private — SignalR event watchers
  // ---------------------------------------------------------------------------

  private watchTaskUpdates(): void {
    const sub = this.signalR.taskUpdated$.subscribe((task) => {
      if (task.newStatus !== 'COMPLETED') return;
      this.add({
        title: `Task completed: ${task.taskName}`,
        tone: 'success',
        route: '/dashboard',
      });
    });
    this.subs.push(sub);
  }

  private watchAlerts(): void {
    const sub = this.signalR.alertCreated$.subscribe((alert) => {
      this.add({
        title: alert.title,
        message: alert.message,
        tone: alert.severity === 'CRITICAL' || alert.severity === 'HIGH' ? 'error' : 'warning',
        route: '/medications',
      });
    });
    this.subs.push(sub);
  }

  private watchAdtEvents(): void {
    const sub = this.signalR.adtEvent$.subscribe((event) => {
      this.add({
        title: `ADT ${event.eventType}: ${event.patientDisplayName}`,
        message: `${event.eventType} — ${event.patientUnit ?? 'Unknown unit'}`,
        tone: 'info',
        route: '/patients',
      });
    });
    this.subs.push(sub);
  }

  private watchBedSuggestions(): void {
    const sub = this.signalR.bedSuggestionCreated$.subscribe((suggestion) => {
      const name = suggestion.patientName ?? suggestion.patient_name ?? 'A patient';
      const unit = suggestion.patientUnit ?? suggestion.patient_unit ?? 'Unknown unit';
      const bed = suggestion.bestBedNumber ?? suggestion.best_bed_number ?? suggestion.bedId ?? suggestion.bed_id ?? '';
      const taskId = suggestion.taskId ?? suggestion.task_id ?? '';
      const encounterId = suggestion.encounterId ?? suggestion.encounter_id ?? '';
      const key = taskId ? `bed-suggestion-${taskId}` : `bed-suggestion-${encounterId}`;
      const id = uuidv4();
      this.add({
        id,
        title: 'ED Boarding Bed Suggestion',
        message: `${name} · Recommended bed ${bed} in ${unit}`,
        tone: 'info',
        route: '/beds',
        key,
        queryParams: { openAssign: 'true', taskId, encounterId, notificationId: id },
      });
    });
    this.subs.push(sub);
  }

  private watchBoardingAlerts(): void {
    const sub = this.signalR.boardingAlertCreated$.subscribe((alert) => {
      const minutes = alert.minutesElapsed ?? alert.minutes_elapsed ?? 0;
      const unit = alert.patientUnit ?? alert.patient_unit ?? 'ED';
      const tone: AppNotification['tone'] =
        alert.severity === 'CRITICAL' || alert.severity === 'HIGH' ? 'error' : 'warning';
      const encounterId = alert.encounterId ?? alert.encounter_id ?? '';
      const key = encounterId ? `boarding-alert-${encounterId}` : `boarding-alert-${alert.alertId ?? alert.alert_id}`;
      const id = uuidv4();
      this.add({
        id,
        title: alert.title || 'ED Boarding Alert',
        message: alert.message || `Patient in ${unit} has been waiting ${minutes} minutes.`,
        tone,
        route: '/beds',
        key,
        queryParams: encounterId
          ? { openAssign: 'true', encounterId, notificationId: id }
          : { openAssign: 'true', notificationId: id },
      });
    });
    this.subs.push(sub);
  }
}
