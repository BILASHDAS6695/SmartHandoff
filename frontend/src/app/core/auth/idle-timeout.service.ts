import { Injectable, OnDestroy, inject } from '@angular/core';
import { DOCUMENT } from '@angular/common';
import { Router } from '@angular/router';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';
import {
  Observable,
  Subscription,
  fromEvent,
  merge,
  timer,
} from 'rxjs';
import { switchMap, take } from 'rxjs/operators';

import { SessionExpiredDialogComponent } from './session-expired-dialog.component';

/** Idle timeout in milliseconds: 30 minutes (US-059, BR-013). */
const IDLE_TIMEOUT_MS = 30 * 60 * 1000;

/**
 * IdleTimeoutService — tracks user inactivity and triggers automatic logout.
 *
 * Security contract (US-059, BR-013):
 *   - Monitors mousemove, keypress, scroll, and touchstart events on `document`.
 *   - Any activity resets the 30-minute countdown via `switchMap`.
 *   - At timeout: `onTimeout` callback is invoked (should call `AuthService.clearSession()`),
 *     a MatDialog modal is displayed for 5 seconds, then the user is redirected to /login.
 *
 * Lifecycle:
 *   - `start()` is called by `AuthService` after successful login.
 *   - `stop()` is called by `AuthService` on user-initiated logout or when
 *     the service fires the idle-timeout logout itself.
 *
 * Design refs:
 *   design.md §8.2 Authentication Flow
 *   SEC-009 (session timeout), BR-013 (30-minute inactivity limit)
 *   US-059 Technical Notes
 */
@Injectable({ providedIn: 'root' })
export class IdleTimeoutService implements OnDestroy {
  private readonly document = inject(DOCUMENT);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);

  private idleSubscription: Subscription | null = null;
  private dialogRef: MatDialogRef<SessionExpiredDialogComponent> | null = null;

  /**
   * Start monitoring user activity. Must be called after successful login.
   *
   * Calling `start()` while already running resets the timer (safe to
   * call on token refresh if implemented in a future story).
   *
   * @param onTimeout Callback invoked when the 30-minute idle timer fires.
   *   Should call `AuthService.clearSession()` to discard the in-memory JWT.
   */
  start(onTimeout: () => void): void {
    this.stop();  // clear any existing subscription before starting

    const activityEvents$: Observable<Event> = merge(
      fromEvent(this.document, 'mousemove'),
      fromEvent(this.document, 'keypress'),
      fromEvent(this.document, 'scroll'),
      fromEvent(this.document, 'touchstart'),  // mobile-first (NFR-033)
    );

    this.idleSubscription = activityEvents$.pipe(
      // Restart the 30-minute timer on every activity event
      switchMap(() => timer(IDLE_TIMEOUT_MS)),
      take(1),  // fire once, then stop subscription
    ).subscribe(() => {
      onTimeout();
      this._showSessionExpiredModal();
    });

    // Dispatch a synthetic event so the switchMap starts immediately —
    // without this the timer would not begin until the first real event.
    this.document.dispatchEvent(new Event('mousemove'));
  }

  /**
   * Stop monitoring user activity. Called on user-initiated logout or when
   * the idle timer fires.
   */
  stop(): void {
    this.idleSubscription?.unsubscribe();
    this.idleSubscription = null;
  }

  /** @internal Open the "Session expired" modal and redirect after 5 seconds. */
  private _showSessionExpiredModal(): void {
    if (this.dialogRef) {
      return;  // already showing — do not open a second modal
    }

    this.dialogRef = this.dialog.open(SessionExpiredDialogComponent, {
      width: '400px',
      disableClose: true,   // user cannot dismiss by clicking backdrop
      ariaLabel: 'Session expired',
    });

    // Auto-dismiss after 5 seconds and redirect to login
    this.dialogRef.afterOpened().pipe(
      switchMap(() => timer(5000)),
      take(1),
    ).subscribe(() => {
      this.dialogRef?.close();
      this.dialogRef = null;
      this.router.navigate(['/login']);
    });

    // Handle manual close (user clicks "Return to Login" button)
    this.dialogRef.afterClosed().pipe(take(1)).subscribe(() => {
      this.dialogRef = null;
      this.router.navigate(['/login']);
    });
  }

  ngOnDestroy(): void {
    this.stop();
  }
}
