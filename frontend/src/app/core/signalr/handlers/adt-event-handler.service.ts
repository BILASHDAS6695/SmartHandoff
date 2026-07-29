/**
 * AdtEventHandlerService — listens to adt_event_received messages from SignalRService
 * and maintains a signal of the last 20 ADT events for the Live ADT Events panel.
 *
 * US-048 TASK-002
 */
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
