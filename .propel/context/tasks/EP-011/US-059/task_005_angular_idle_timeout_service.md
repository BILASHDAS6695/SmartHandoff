---
id: TASK-005
title: "Implement Angular `IdleTimeoutService` + 'Session Expired' Modal"
user_story: US-059
epic: EP-011
sprint: 1
layer: Frontend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Frontend Engineer
upstream: [US-056/TASK-005, US-056/TASK-006]
---

# TASK-005: Implement Angular `IdleTimeoutService` + "Session Expired" Modal

> **Story:** US-059 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Frontend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AC Scenario 3 requires that after 30 minutes of inactivity (no `mousemove`, `keypress`, or `scroll` events), the Angular app:
1. Clears the in-memory JWT from `AuthService` (US-056/TASK-005).
2. Displays a "Session expired" `MatDialog` modal.
3. Redirects the user to the login page.

US-059 Technical Notes specify the implementation pattern:
```
Angular fromEvent(document, 'mousemove') merged with keypress/scroll;
switchMap(() => timer(1800000)) fires after 30 minutes of no events
```

`IdleTimeoutService` is a singleton (`providedIn: 'root'`). It is **started** by `AuthService` immediately after a successful login and **stopped** on logout (both user-initiated and idle-timeout-triggered). The service must not run when no user is authenticated to avoid false-positive timeouts on the login page.

---

## Acceptance Criteria Addressed

| US-059 AC | Requirement |
|---|---|
| **Scenario 3** | After 30 minutes idle: JWT cleared, "Session expired" modal shown, redirect to login |
| **DoD** | Angular `IdleTimeoutService`: RxJS timer resets on any `mousemove`/`keypress`/`scroll`; fires logout at 30 minutes |
| **DoD** | "Session expired" modal: `MatDialog` with auto-dismiss and redirect to login |

---

## Implementation Steps

### 1. Create `frontend/src/app/core/auth/idle-timeout.service.ts`

```typescript
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
 *   - Monitors mousemove, keypress, and scroll events on `document`.
 *   - Any activity resets the 30-minute countdown via `switchMap`.
 *   - At timeout: `AuthService.clearSession()` is called, a MatDialog modal
 *     is displayed for 5 seconds, then the user is redirected to /login.
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
   */
  start(onTimeout: () => void): void {
    this.stop();  // clear any existing subscription

    const activityEvents$: Observable<Event> = merge(
      fromEvent(this.document, 'mousemove'),
      fromEvent(this.document, 'keypress'),
      fromEvent(this.document, 'scroll'),
      fromEvent(this.document, 'touchstart'),  // mobile-first (NFR-033)
    );

    this.idleSubscription = activityEvents$.pipe(
      // Restart the 30-minute timer on every activity event
      switchMap(() => timer(IDLE_TIMEOUT_MS)),
      take(1),  // fire once, then let caller decide to restart
    ).subscribe(() => {
      onTimeout();
      this._showSessionExpiredModal();
    });

    // Fire immediately from a synthetic source so the timer starts
    // even if no activity event occurs before the first real event.
    this.document.dispatchEvent(new Event('mousemove'));
  }

  /**
   * Stop monitoring. Called on user-initiated logout or when idle fires.
   */
  stop(): void {
    this.idleSubscription?.unsubscribe();
    this.idleSubscription = null;
  }

  private _showSessionExpiredModal(): void {
    if (this.dialogRef) {
      return;  // already showing
    }
    this.dialogRef = this.dialog.open(SessionExpiredDialogComponent, {
      width: '400px',
      disableClose: true,
      ariaLabel: 'Session expired',
    });

    // Auto-dismiss after 5 seconds and redirect
    this.dialogRef.afterOpened().pipe(
      switchMap(() => timer(5000)),
      take(1),
    ).subscribe(() => {
      this.dialogRef?.close();
      this.dialogRef = null;
      this.router.navigate(['/login']);
    });

    // Also handle manual close (user presses button)
    this.dialogRef.afterClosed().pipe(take(1)).subscribe(() => {
      this.dialogRef = null;
      this.router.navigate(['/login']);
    });
  }

  ngOnDestroy(): void {
    this.stop();
  }
}
```

---

### 2. Create `frontend/src/app/core/auth/session-expired-dialog.component.ts`

```typescript
import { Component } from '@angular/core';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';

/**
 * SessionExpiredDialogComponent — auto-dismissing "Session expired" modal.
 *
 * Displayed by IdleTimeoutService when the 30-minute idle timer fires.
 * Auto-dismissed after 5 seconds; also has a manual "Return to Login"
 * button for immediate navigation.
 *
 * Accessibility:
 *   - role="alertdialog" with aria-live="assertive" for screen reader announcement
 *   - MatDialog handles focus trap automatically (WCAG 2.1 AA, NFR-034)
 */
@Component({
  selector: 'app-session-expired-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule],
  template: `
    <div role="alertdialog" aria-live="assertive" aria-labelledby="session-expired-title">
      <h2 id="session-expired-title" mat-dialog-title>Session Expired</h2>
      <mat-dialog-content>
        <p>
          Your session has expired due to 30 minutes of inactivity.
          You will be redirected to the login page.
        </p>
      </mat-dialog-content>
      <mat-dialog-actions align="end">
        <button
          mat-flat-button
          color="primary"
          (click)="dialogRef.close()"
          aria-label="Return to login page"
        >
          Return to Login
        </button>
      </mat-dialog-actions>
    </div>
  `,
})
export class SessionExpiredDialogComponent {
  constructor(readonly dialogRef: MatDialogRef<SessionExpiredDialogComponent>) {}
}
```

---

### 3. Update `AuthService` — Wire `IdleTimeoutService`

In `frontend/src/app/core/auth/auth.service.ts` (US-056/TASK-005), inject and wire `IdleTimeoutService`:

```typescript
import { inject } from '@angular/core';
import { IdleTimeoutService } from './idle-timeout.service';

// Inside AuthService class body:
private readonly idleTimeoutService = inject(IdleTimeoutService);

// After successful login (inside the method that stores the JWT):
private _setSession(token: string): void {
  this.#token = token;
  this.#isAuthenticated.set(true);

  // Start the 30-minute idle timer (US-059)
  this.idleTimeoutService.start(() => {
    this._clearSession();  // clear in-memory JWT on timeout
  });
}

// Update the logout / clearSession method:
clearSession(): void {
  this.#token = null;
  this.#isAuthenticated.set(false);
  this.idleTimeoutService.stop();
}
```

> **Naming note:** Adapt method names to match whatever `AuthService` uses from US-056/TASK-005 — the key constraint is that `idleTimeoutService.start()` is called when the JWT is stored and `idleTimeoutService.stop()` is called when it is cleared.

---

## Validation

```bash
cd frontend

# 1. TypeScript strict-mode compilation — no errors
npx ng build --configuration=development 2>&1 | grep -E "ERROR|WARNING"

# 2. Jest unit tests — IdleTimeoutService (TASK-006 adds full tests)
npx jest --testPathPattern="idle-timeout" --passWithNoTests

# 3. Angular Material dialog import check
npx ng build 2>&1 | grep -c "ERROR" && echo "Build errors found" || echo "Build: OK"
```
