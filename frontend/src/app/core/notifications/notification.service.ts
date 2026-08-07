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

/** Initial demo notifications aligned with the SCR-002 wireframe. */
const INITIAL_NOTIFICATIONS: AppNotification[] = [
  {
    id: 'notif-1',
    title: 'New discharge task assigned',
    message: 'Smith, John · Unit 4W',
    tone: 'info',
    read: false,
    timestamp: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
    route: '/patients',
  },
  {
    id: 'notif-2',
    title: 'Medication conflict needs review',
    message: 'Warfarin + Aspirin · Nguyen, Lee',
    tone: 'error',
    read: false,
    timestamp: new Date(Date.now() - 12 * 60 * 1000).toISOString(),
    route: '/medications',
  },
  {
    id: 'notif-3',
    title: 'Patient message received',
    message: 'Garcia, Maria via portal',
    tone: 'success',
    read: false,
    timestamp: new Date(Date.now() - 35 * 60 * 1000).toISOString(),
    route: '/portal',
  },
];

@Injectable({ providedIn: 'root' })
export class NotificationService implements OnDestroy {
  private readonly signalR = inject(SignalRService);

  private readonly _notifications = signal<AppNotification[]>(INITIAL_NOTIFICATIONS);
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
  }

  ngOnDestroy(): void {
    this.subs.forEach((s) => s.unsubscribe());
  }

  /**
   * Add a new notification.
   * @param notification Partial notification; id and timestamp are auto-populated.
   */
  add(notification: Omit<AppNotification, 'id' | 'timestamp' | 'read'> & Partial<Pick<AppNotification, 'read'>>): void {
    const next: AppNotification = {
      id: uuidv4(),
      read: false,
      timestamp: new Date().toISOString(),
      ...notification,
    };
    this._notifications.update((current) => [next, ...current]);
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
}
