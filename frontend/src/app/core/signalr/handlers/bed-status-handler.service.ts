/**
 * BedStatusHandlerService — listens to bed_status_changed messages from SignalRService
 * and maintains a map of bed statuses keyed by bedId.
 *
 * US-048 TASK-002
 */
import { Injectable, OnDestroy, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { SignalRService } from '../signalr.service';
import { BedStatusChangedPayload } from '../signalr.models';

/**
 * Listens to `bedStatusChanged$` and maintains a map of bed statuses keyed by bedId.
 * Bed status components can query this map to reflect real-time bed availability.
 */
@Injectable({ providedIn: 'root' })
export class BedStatusHandlerService implements OnDestroy {
  private readonly signalR = inject(SignalRService);
  private readonly sub: Subscription;

  private readonly _bedStatusMap = signal<Map<string, BedStatusChangedPayload>>(
    new Map(),
  );

  /** All bed statuses indexed by bedId. */
  readonly bedStatusMap = computed(() => this._bedStatusMap());

  /** Beds in AVAILABLE status. */
  readonly availableBeds = computed(() =>
    Array.from(this._bedStatusMap().values()).filter(
      (b) => b.status === 'AVAILABLE',
    ),
  );

  constructor() {
    this.sub = this.signalR.bedStatusChanged$.subscribe((bedStatus) => {
      this._bedStatusMap.update((map) => {
        const next = new Map(map);
        next.set(bedStatus.bedId, bedStatus);
        return next;
      });
    });
  }

  /**
   * Returns the latest status for a given bed ID.
   * Returns `null` if no update has been received for this bed.
   */
  getBedStatus(bedId: string): BedStatusChangedPayload | null {
    return this._bedStatusMap().get(bedId) ?? null;
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }
}
