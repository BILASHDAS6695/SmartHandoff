import { Injectable, inject, OnDestroy } from '@angular/core';
import { SignalRService } from '@core/signalr/signalr.service';
import { BedUpdateEvent } from '../models/bed.model';
import { Subject, Subscription } from 'rxjs';

/**
 * UpdateCallback type — callback signature for bed status updates.
 * Strongly typed callback to ensure safe invocation of bed state mutations.
 */
type UpdateCallback = (event: BedUpdateEvent) => void;

/**
 * BedRealtimeService — Subscribes to SignalR bed_status_changed events
 * and delegates cell state updates to BedBoardComponent via callback.
 * Satisfies US-050 Scenario 2: bed cell updates within 1 second of ADT event.
 *
 * Usage:
 *   constructor(private bedRealtime: BedRealtimeService) {}
 *   ngOnInit() {
 *     this.bedRealtime.start((event) => this.updateBedStatus(event.bedId, patch));
 *   }
 *   ngOnDestroy() {
 *     this.bedRealtime.stop();
 *   }
 */
@Injectable({ providedIn: 'root' })
export class BedRealtimeService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private updateCallback: UpdateCallback | null = null;
  private subscription: Subscription | null = null;

  /**
   * Registers the update callback and subscribes to the SignalR event stream.
   * Call once from BedBoardComponent.ngOnInit() after initial data load.
   * @param onUpdate Callback invoked each time a bed_status_changed event is received.
   */
  start(onUpdate: UpdateCallback): void {
    this.updateCallback = onUpdate;
    this.subscription = this.signalR.bedStatusChanged$.subscribe((event) => {
      // Map BedStatusChangedPayload to BedUpdateEvent
      const bedUpdateEvent: BedUpdateEvent = {
        bedId: event.bedId,
        status: event.status as any,
        patientName: '',
        predictedDischargeTime: null,
      };
      this.updateCallback?.(bedUpdateEvent);
    });
  }

  /**
   * Unsubscribes from the SignalR event stream and nulls the callback.
   * Call from BedBoardComponent.ngOnDestroy() to prevent memory leaks.
   */
  stop(): void {
    if (this.subscription) {
      this.subscription.unsubscribe();
      this.subscription = null;
    }
    this.updateCallback = null;
  }

  ngOnDestroy(): void {
    this.stop();
  }
}
