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
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { interval, Subscription, takeWhile } from 'rxjs';
import { environment } from '../../../../environments/environment';

interface VerifyResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

interface ErrorResponse {
  detail?: string;
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
    return this.digits().every((d: string) => d.length === 1);
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
        // If current input has content, clear it
        updated[index] = '';
        this.digits.set(updated);
      } else if (index > 0) {
        // If current is empty, move back and clear previous
        updated[index - 1] = '';
        this.digits.set(updated);
        this.focusInput(index - 1);
      }
      event.preventDefault();
    }
  }

  onPaste(event: ClipboardEvent): void {
    const pasted = event.clipboardData?.getData('text') ?? '';
    const digits = pasted.replace(/\D/g, '').split('').slice(0, 6);

    if (digits.length > 0) {
      this.digits.set(
        digits.concat(Array(6 - digits.length).fill(''))
      );
      event.preventDefault();

      // Auto-submit if all 6 digits pasted
      if (digits.length === 6) {
        this.submit();
      }
    }
  }

  async submit(): Promise<void> {
    if (!this.isComplete || this.isSubmitting()) {
      return;
    }

    this.isSubmitting.set(true);
    this.errorMessage.set(null);

    const otp = this.digits().join('');

    try {
      const response = await this.http.post<VerifyResponse>(
        `${environment.apiBaseUrl}/api/v1/auth/patient/verify`,
        {
          portal_token: this.portalToken,
          otp,
        }
      ).toPromise();

      if (!response) {
        throw new Error('No response from server');
      }

      // Store JWT in sessionStorage (NOT localStorage) — OWASP A02
      sessionStorage.setItem('patient_jwt', response.access_token);
      sessionStorage.setItem('jwt_expires_in', String(response.expires_in));

      // Navigate to patient portal home
      this.router.navigate(['/portal/home']);
    } catch (error: unknown) {
      this.isSubmitting.set(false);

      if (error instanceof HttpErrorResponse) {
        const detail = (error.error as ErrorResponse)?.detail ?? 'An error occurred';

        if (error.status === 401) {
          if (detail.toLowerCase().includes('expired')) {
            this.errorMessage.set('Your code has expired. Request a new one.');
            this.isExpired.set(true);
          } else {
            this.errorMessage.set('Incorrect code. Please try again.');
            // Do not clear inputs on mismatch
          }
        } else {
          this.errorMessage.set('An error occurred. Please try again.');
        }
      } else {
        this.errorMessage.set('An error occurred. Please try again.');
      }
    }
  }

  requestNewOtp(): void {
    // Reset the component
    this.digits.set(['', '', '', '', '', '']);
    this.errorMessage.set(null);
    this.isExpired.set(false);
    this.isSubmitting.set(false);
    this.remainingSeconds.set(600);

    // Restart countdown
    this.timerSub?.unsubscribe();
    this.startCountdown();

    // Trigger OTP generation
    this.http.post(
      `${environment.apiBaseUrl}/api/v1/auth/patient/otp`,
      { portal_token: this.portalToken }
    ).subscribe({
      error: (err: unknown) => {
        this.errorMessage.set('Failed to request OTP. Please try again.');
      },
    });

    // Focus first input
    setTimeout(() => this.focusInput(0), 100);
  }

  private focusInput(index: number): void {
    const inputs = this.otpInputs.toArray();
    if (inputs[index]) {
      inputs[index].nativeElement.focus();
    }
  }

  private startCountdown(): void {
    this.timerSub = interval(1000)
      .pipe(
        takeWhile(() => this.remainingSeconds() > 0)
      )
      .subscribe(() => {
        const remaining = this.remainingSeconds() - 1;
        this.remainingSeconds.set(remaining);

        if (remaining === 0) {
          this.isExpired.set(true);
          this.disableInputs();
          this.errorMessage.set('Your code has expired. Request a new one.');
        }
      });
  }

  private disableInputs(): void {
    const inputs = this.otpInputs.toArray();
    inputs.forEach((input: ElementRef<HTMLInputElement>) => {
      input.nativeElement.disabled = true;
    });
  }
}

