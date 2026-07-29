/**
 * NetworkStatusService — reactive online/offline connectivity tracking (US-054).
 *
 * Exposes a readonly `isOffline` signal derived from browser `online`/`offline`
 * window events. Components import this service to conditionally render offline
 * UI elements without polling.
 *
 * Design refs:
 *   US-054 Scenario 2      — offline banner trigger
 *   design.md §3.4 core/   — singleton service boundary
 *   web-accessibility-standards — aria-live status announcement
 */
import { Injectable, OnDestroy, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class NetworkStatusService implements OnDestroy {
  /** True when the browser reports the network is unavailable. */
  readonly isOffline = signal<boolean>(!navigator.onLine);

  private readonly onOnline = (): void => this.isOffline.set(false);
  private readonly onOffline = (): void => this.isOffline.set(true);

  constructor() {
    window.addEventListener('online', this.onOnline);
    window.addEventListener('offline', this.onOffline);
  }

  ngOnDestroy(): void {
    window.removeEventListener('online', this.onOnline);
    window.removeEventListener('offline', this.onOffline);
  }
}
