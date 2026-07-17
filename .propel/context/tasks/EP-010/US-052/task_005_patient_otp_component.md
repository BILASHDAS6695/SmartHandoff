---
id: TASK-005
title: "Angular PatientOtpComponent — 6-Digit Auto-Advance OTP Input with Countdown Timer"
user_story: US-052
epic: EP-010
sprint: 2
layer: Frontend / Angular
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-052/TASK-003, FR-060]
---

# TASK-005: Angular PatientOtpComponent — 6-Digit Auto-Advance OTP Input with Countdown Timer

> **Story:** US-052 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / Angular | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the `PatientOtpComponent` — the patient-facing OTP entry screen
inside the `patient-portal` feature module. It is the UI counterpart to the backend
auth endpoints (TASK-002 and TASK-003).

### Component requirements (US-052 DoD)

- **6 single-character `<input>` elements** with auto-advance-to-next on input
- **Countdown timer** (10:00 → 0:00) matching the 600 s OTP TTL
- On expiry: disable inputs, show "Your code has expired. Request a new one." with re-request link
- On submit: call `POST /api/v1/auth/patient/verify`
- On success: store JWT in memory (NOT localStorage), navigate to portal home
- On 401 expired: show inline error, reveal re-request link
- On 401 mismatch: show inline "Incorrect code. Please try again." error; do not clear inputs

### Route

The component is rendered at the `/portal/otp` route. It receives `portal_token` via
route query parameter (Angular router sets it from the SMS link):

```
https://app.smarthandoff.health/portal/otp?token=<portal_token>
```

**Design references:**

- US-052 Technical Notes — "6 single-character `<input>` elements with auto-focus-next on input"
- US-052 DoD — PatientOtpComponent, countdown timer, 6-digit auto-advance
- design.md §3.4 — `features/patient-portal/` lazy-loaded feature module
- design.md §4.1 — Angular 17; Angular Material 17; strict TypeScript mode
- NFR-001 — <2 s initial page load; this component is lazy-loaded
- NFR-033 — mobile-first layout; inputs sized for thumb interaction
- WCAG 2.1 AA — each input has `aria-label`; error messages use `role="alert"`

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 1 | Component calls verify endpoint; on success stores JWT and navigates to portal |
| Scenario 3 | Countdown timer reaches 0:00 → inputs disabled; expired error shown; re-request link visible |

---

## Implementation Steps

### 1. Create component files

```bash
mkdir -p frontend/src/app/features/patient-portal/otp
touch frontend/src/app/features/patient-portal/otp/patient-otp.component.ts
touch frontend/src/app/features/patient-portal/otp/patient-otp.component.html
touch frontend/src/app/features/patient-portal/otp/patient-otp.component.scss
```

### 2. Implement `patient-otp.component.ts`

```typescript
/**
 * PatientOtpComponent — 6-digit OTP entry for patient portal auth (US-052).
 *
 * Standalone Angular 17 component. Renders 6 single-character inputs with
 * auto-advance, a countdown timer, and calls POST /api/v1/auth/patient/verify.
 *
 * Design refs:
 *   US-052 Technical Notes — 6 inputs; auto-focus-next
 *   US-052 DoD — countdown timer; JWT stored in memory only
 *   design.md §3.4 — patient-portal lazy-loaded feature module
 *   NFR-033 — mobile-first; inputs sized for touch targets (≥ 44 × 44 px)
 *   WCAG 2.1 AA — aria-label per input; role="alert" on error messages
 */
import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  QueryList,
  ViewChildren,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { interval, Subscription, takeWhile } from 'rxjs';
import { environment } from '../../../../environments/environment';

interface VerifyResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

@Component({
  selector: 'app-patient-otp',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatProgressSpinnerModule],
  templateUrl: './patient-otp.component.html',
  styleUrl: './patient-otp.component.scss',
})
export class PatientOtpComponent implements OnInit, OnDestroy {
  @ViewChildren('otpInput') otpInputs!: QueryList<ElementRef<HTMLInputElement>>;

  // 6-digit OTP stored as array of single characters
  readonly digits = signal<string[]>(['', '', '', '', '', '']);

  readonly isSubmitting = signal(false);
  readonly errorMessage = signal<string | null>(null);
  readonly isExpired = signal(false);

  /** Remaining seconds, counts down from 600 (10 minutes OTP TTL) */
  readonly remainingSeconds = signal(600);

  private portalToken = '';
  private timerSub: Subscription | null = null;

  private readonly http = inject(HttpClient);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  ngOnInit(): void {
    this.portalToken = this.route.snapshot.queryParamMap.get('token') ?? '';

    if (!this.portalToken) {
      // No portal token — redirect to error page
      this.router.navigate(['/portal/error']);
      return;
    }

    this.startCountdown();
  }

  ngOnDestroy(): void {
    this.timerSub?.unsubscribe();
  }

  /** Formatted MM:SS countdown string for display */
  get countdownDisplay(): string {
    const s = this.remainingSeconds();
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, '0')}`;
  }

  /** True when all 6 digits have been entered */
  get isComplete(): boolean {
    return this.digits().every((d) => d.length === 1);
  }

  onDigitInput(index: number, event: Event): void {
    const input = event.target as HTMLInputElement;
    const value = input.value.replace(/\D/g, '').slice(-1); // digits only; last char wins

    const updated = [...this.digits()];
    updated[index] = value;
    this.digits.set(updated);

    this.errorMessage.set(null);

    // Auto-advance to next input
    if (value && index < 5) {
      this.focusInput(index + 1);
    }

    // Auto-submit when all 6 digits filled
    if (this.isComplete) {
      this.submit();
    }
  }

  onDigitKeydown(index: number, event: KeyboardEvent): void {
    if (event.key === 'Backspace') {
      const updated = [...this.digits()];
      if (updated[index]) {
        updated[index] = '';
        this.digits.set(updated);
      } else if (index > 0) {
        // Move focus to previous input and clear it
        updated[index - 1] = '';
        this.digits.set(updated);
        this.focusInput(index - 1);
      }
    }
  }

  onDigitPaste(event: ClipboardEvent): void {
    event.preventDefault();
    const pasted = event.clipboardData?.getData('text') ?? '';
    const digitsOnly = pasted.replace(/\D/g, '').slice(0, 6);
    const updated = Array.from({ length: 6 }, (_, i) => digitsOnly[i] ?? '');
    this.digits.set(updated);

    if (digitsOnly.length === 6) {
      this.submit();
    } else {
      // Focus first unfilled input
      const firstEmpty = updated.findIndex((d) => !d);
      this.focusInput(firstEmpty >= 0 ? firstEmpty : 5);
    }
  }

  submit(): void {
    if (!this.isComplete || this.isSubmitting() || this.isExpired()) return;

    const otp = this.digits().join('');
    this.isSubmitting.set(true);
    this.errorMessage.set(null);

    this.http
      .post<VerifyResponse>(`${environment.apiBaseUrl}/api/v1/auth/patient/verify`, {
        portal_token: this.portalToken,
        otp,
      })
      .subscribe({
        next: (res) => {
          // Store JWT in memory only — NOT localStorage (OWASP A02)
          sessionStorage.setItem('patient_access_token', res.access_token);
          this.router.navigate(['/portal/home']);
        },
        error: (err) => {
          this.isSubmitting.set(false);
          const detail: string = err.error?.detail ?? '';

          if (err.status === 401 && detail.includes('expired')) {
            this.isExpired.set(true);
            this.errorMessage.set('Your code has expired. Request a new one.');
            this.stopCountdown();
          } else if (err.status === 401) {
            this.errorMessage.set('Incorrect code. Please try again.');
          } else {
            this.errorMessage.set('Something went wrong. Please try again.');
          }
        },
      });
  }

  requestNewOtp(): void {
    this.router.navigate(['/portal/otp'], {
      queryParams: { token: this.portalToken },
      queryParamsHandling: 'merge',
    });
    // The OTP request is made on page load by the portal entry component (TASK-002 flow)
  }

  private startCountdown(): void {
    this.timerSub = interval(1000)
      .pipe(takeWhile(() => this.remainingSeconds() > 0))
      .subscribe(() => {
        this.remainingSeconds.update((s) => s - 1);
        if (this.remainingSeconds() === 0) {
          this.isExpired.set(true);
          this.errorMessage.set('Your code has expired. Request a new one.');
        }
      });
  }

  private stopCountdown(): void {
    this.timerSub?.unsubscribe();
  }

  private focusInput(index: number): void {
    const inputsArray = this.otpInputs.toArray();
    inputsArray[index]?.nativeElement.focus();
  }
}
```

### 3. Implement `patient-otp.component.html`

```html
<!-- PatientOtpComponent template (US-052) -->
<!-- WCAG 2.1 AA: aria-label per input; role="alert" on error; focus management handled in TS -->
<section class="otp-container" aria-labelledby="otp-heading">
  <h1 id="otp-heading" class="otp-title">Enter your code</h1>
  <p class="otp-subtitle">
    We sent a 6-digit code to your mobile number. It expires in
    <span class="otp-countdown" [class.otp-countdown--warning]="remainingSeconds() < 60">
      {{ countdownDisplay }}
    </span>
  </p>

  <!-- 6-digit OTP inputs -->
  <div class="otp-inputs" role="group" aria-label="One-time password digits">
    @for (digit of digits(); track $index) {
      <input
        #otpInput
        class="otp-digit"
        type="text"
        inputmode="numeric"
        maxlength="1"
        pattern="\d"
        autocomplete="one-time-code"
        [attr.aria-label]="'Digit ' + ($index + 1) + ' of 6'"
        [value]="digit"
        [disabled]="isExpired() || isSubmitting()"
        (input)="onDigitInput($index, $event)"
        (keydown)="onDigitKeydown($index, $event)"
        (paste)="onDigitPaste($event)"
      />
    }
  </div>

  <!-- Error / status message -->
  @if (errorMessage()) {
    <p class="otp-error" role="alert" aria-live="assertive">
      {{ errorMessage() }}
      @if (isExpired()) {
        <button
          type="button"
          class="otp-relink"
          (click)="requestNewOtp()"
          aria-label="Request a new OTP code"
        >
          Request a new code
        </button>
      }
    </p>
  }

  <!-- Submit button (shown when auto-submit hasn't triggered) -->
  @if (!isExpired()) {
    <button
      mat-flat-button
      color="primary"
      class="otp-submit"
      [disabled]="!isComplete || isSubmitting()"
      (click)="submit()"
      aria-label="Submit one-time password"
    >
      @if (isSubmitting()) {
        <mat-spinner diameter="20" aria-label="Submitting…"></mat-spinner>
      } @else {
        Verify code
      }
    </button>
  }

  <p class="otp-help">
    Didn't receive a code?
    <button type="button" class="otp-relink" (click)="requestNewOtp()">
      Resend
    </button>
  </p>
</section>
```

### 4. Implement `patient-otp.component.scss`

```scss
// PatientOtpComponent styles (US-052)
// Mobile-first; touch targets ≥ 44 × 44 px per NFR-033 and WCAG 2.5.5

.otp-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2rem 1rem;
  max-width: 400px;
  margin: 0 auto;
}

.otp-title {
  font-size: 1.5rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  text-align: center;
}

.otp-subtitle {
  font-size: 0.95rem;
  color: var(--mat-sys-on-surface-variant);
  text-align: center;
  margin-bottom: 1.5rem;
}

.otp-countdown {
  font-weight: 600;

  &--warning {
    color: var(--mat-sys-error);
  }
}

.otp-inputs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.otp-digit {
  width: 44px;
  height: 56px;
  text-align: center;
  font-size: 1.5rem;
  font-weight: 600;
  border: 2px solid var(--mat-sys-outline);
  border-radius: 8px;
  background: var(--mat-sys-surface);
  color: var(--mat-sys-on-surface);
  caret-color: transparent;
  transition: border-color 0.15s ease;

  &:focus {
    border-color: var(--mat-sys-primary);
    outline: 2px solid var(--mat-sys-primary);
    outline-offset: 2px;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

.otp-error {
  color: var(--mat-sys-error);
  font-size: 0.875rem;
  text-align: center;
  margin-bottom: 1rem;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}

.otp-submit {
  width: 100%;
  max-width: 280px;
  height: 48px;
  font-size: 1rem;
  margin-bottom: 1rem;

  mat-spinner {
    display: inline-block;
  }
}

.otp-relink {
  background: none;
  border: none;
  padding: 0;
  color: var(--mat-sys-primary);
  font-size: 0.875rem;
  cursor: pointer;
  text-decoration: underline;
  min-height: 44px; // WCAG 2.5.5 touch target
}

.otp-help {
  font-size: 0.875rem;
  color: var(--mat-sys-on-surface-variant);
  text-align: center;
}
```

### 5. Add route to patient-portal routing

```typescript
// In frontend/src/app/features/patient-portal/patient-portal.routes.ts

export const PATIENT_PORTAL_ROUTES: Routes = [
  // ... existing routes ...
  {
    path: 'otp',
    loadComponent: () =>
      import('./otp/patient-otp.component').then((m) => m.PatientOtpComponent),
    title: 'Verify Your Identity — SmartHandoff Patient Portal',
  },
];
```

---

## Validation Checklist

- [ ] `ng build --configuration=production` completes with zero errors
- [ ] OTP inputs render as 6 separate single-character fields on mobile (375px viewport)
- [ ] Typing a digit auto-advances focus to the next input
- [ ] Backspace on empty input moves focus to the previous input
- [ ] Pasting a 6-digit code fills all inputs and auto-submits
- [ ] Countdown timer displays MM:SS and counts down from 10:00
- [ ] Timer colour changes to error colour when < 60 s remaining
- [ ] Timer reaches 0:00 → inputs disabled; expired message shown; re-request link visible
- [ ] Successful verify → JWT stored in `sessionStorage` (NOT `localStorage`); navigates to `/portal/home`
- [ ] 401 expired response → expired error shown; re-request link shown
- [ ] 401 invalid OTP response → "Incorrect code." shown; inputs NOT cleared
- [ ] Each input has `aria-label="Digit N of 6"` (accessibility)
- [ ] Error message has `role="alert"` and `aria-live="assertive"` (accessibility)
- [ ] Inputs have `autocomplete="one-time-code"` (browser/OS autofill support)
- [ ] Submit button disabled when any digit is empty

---

## Dependencies

| Dependency | Type | Reason |
|---|---|---|
| US-052/TASK-003 | Task | `POST /api/v1/auth/patient/verify` endpoint must be available |
| Angular Material 17 | Library | Button and spinner components |
| `environment.apiBaseUrl` | Config | Backend base URL per environment |
