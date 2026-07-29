/**
 * PwaInstallPromptService — captures and defers the BeforeInstallPromptEvent
 * so the patient-portal install button can trigger it on demand (US-054).
 *
 * The browser fires BeforeInstallPromptEvent only once per session when PWA
 * install criteria are met. This service stores the event reference so that
 * the install button can call prompt() at a user-initiated moment.
 *
 * Design refs:
 *   US-054 Scenario 4  — install prompt appears; app installs to home screen
 *   US-054 DoD         — BeforeInstallPromptEvent handled; "Add to Home Screen" shown
 *   design.md ADR-005  — Angular 17 PWA
 */
import { Injectable, OnDestroy, signal } from '@angular/core';

/** Minimal interface for the non-standard BeforeInstallPromptEvent. */
interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[];
  prompt(): Promise<void>;
  readonly userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

@Injectable({ providedIn: 'root' })
export class PwaInstallPromptService implements OnDestroy {
  /** True when the deferred install prompt is available for triggering. */
  readonly canInstall = signal<boolean>(false);

  private deferredPrompt: BeforeInstallPromptEvent | null = null;

  private readonly onBeforeInstallPrompt = (event: Event): void => {
    event.preventDefault();
    this.deferredPrompt = event as BeforeInstallPromptEvent;
    this.canInstall.set(true);
  };

  private readonly onAppInstalled = (): void => {
    this.deferredPrompt = null;
    this.canInstall.set(false);
  };

  constructor() {
    window.addEventListener('beforeinstallprompt', this.onBeforeInstallPrompt);
    window.addEventListener('appinstalled', this.onAppInstalled);
  }

  ngOnDestroy(): void {
    window.removeEventListener('beforeinstallprompt', this.onBeforeInstallPrompt);
    window.removeEventListener('appinstalled', this.onAppInstalled);
  }

  /**
   * Shows the install prompt to the user.
   * Must be called from a user-initiated event (click handler).
   */
  async prompt(): Promise<void> {
    if (!this.deferredPrompt) {
      return;
    }
    await this.deferredPrompt.prompt();
    const { outcome } = await this.deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      this.deferredPrompt = null;
      this.canInstall.set(false);
    }
  }
}
