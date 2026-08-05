import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../../../core/auth/auth.service';
import { environment } from '../../../../environments/environment';

interface OidcTokenResponse {
  id_token: string;
  access_token: string;
  token_type: string;
  expires_in: number;
}

/**
 * LoginCallbackComponent — handles the OIDC redirect from the IdP.
 *
 * Lifecycle:
 *   1. Read `code` and `state` from query params.
 *   2. Validate `state` matches sessionStorage `oidc_state` (CSRF protection).
 *   3. Retrieve `pkce_code_verifier` from sessionStorage.
 *   4. POST to IdP token endpoint to exchange code for id_token (PKCE flow).
 *   5. Call AuthService.exchangeIdToken(id_token) to get SmartHandoff app JWT.
 *   6. Clear PKCE artefacts from sessionStorage.
 *   7. Navigate to dashboard (or returnUrl if present).
 *
 * Error handling: Any failure redirects to /login with an error query param.
 */
@Component({
  selector: 'app-login-callback',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="callback-container" role="main" aria-label="Completing sign-in">
      <p *ngIf="!error">Completing sign-in…</p>
      <p *ngIf="error" role="alert" aria-live="assertive">
        Sign-in failed. Redirecting to login page…
      </p>
    </div>
  `,
})
export class LoginCallbackComponent implements OnInit {
  error = false;

  constructor(
    private readonly route: ActivatedRoute,
    private readonly router: Router,
    private readonly http: HttpClient,
    private readonly authService: AuthService,
  ) {}

  async ngOnInit(): Promise<void> {
    try {
      await this.#handleCallback();
    } catch (err) {
      if (err instanceof HttpErrorResponse) {
        const backendDetail = err.error?.detail || err.error?.message || JSON.stringify(err.error);
        console.error('❌ OIDC callback exchange failed', {
          status: err.status,
          statusText: err.statusText,
          detail: backendDetail,
          rawError: err.error,
        });
        
        // Log more details about the error
        if (err.status === 400) {
          console.error('💡 400 Bad Request likely means: Invalid authorization code, expired code, or mismatched redirect_uri');
        } else if (err.status === 401) {
          console.error('💡 401 Unauthorized: Client authentication failed or authorization code is invalid');
        }
      } else {
        console.error('❌ OIDC callback error:', err);
      }
      this.error = true;
      // Clean up PKCE artefacts on failure
      sessionStorage.removeItem('pkce_code_verifier');
      sessionStorage.removeItem('oidc_state');
      setTimeout(() => this.router.navigate(['/login', { error: 'auth_failed' }]), 2000);
    }
  }

  async #handleCallback(): Promise<void> {
    const params = this.route.snapshot.queryParams;
    const code: string | undefined = params['code'];
    const returnedState: string | undefined = params['state'];
    const error: string | undefined = params['error'];

    // Handle IdP error response (e.g. user denied consent)
    if (error) {
      throw new Error(`IdP returned error: ${error} — ${params['error_description'] ?? ''}`);
    }

    if (!code) {
      throw new Error('No authorization code in callback URL');
    }

    // CSRF: validate state parameter
    const expectedState = sessionStorage.getItem('oidc_state');
    if (!expectedState || returnedState !== expectedState) {
      throw new Error('State mismatch — possible CSRF attack');
    }

    // Retrieve PKCE verifier
    const codeVerifier = sessionStorage.getItem('pkce_code_verifier');
    if (!codeVerifier) {
      throw new Error('PKCE code_verifier missing from session storage');
    }

    // Exchange code for tokens via backend (secure - keeps client_secret on server)
    const codeExchangeBody = {
      code,
      code_verifier: codeVerifier,
      redirect_uri: `${window.location.origin}/auth/callback`,
    };

    // Ensure proper JSON encoding and headers
    console.log('📤 Sending code exchange request with body:', {
      code: codeExchangeBody.code.substring(0, 20) + '...',
      code_verifier: codeExchangeBody.code_verifier.substring(0, 20) + '...',
      redirect_uri: codeExchangeBody.redirect_uri,
    });

    try {
      const tokenResponse = await firstValueFrom(
        this.http.post<{ access_token: string; token_type: string; expires_in: number }>(
          `${environment.apiBaseUrl}/api/v1/auth/exchange-code`,
          codeExchangeBody,
          { 
            headers: { 'Content-Type': 'application/json' },
            withCredentials: true,
          }
        )
      );

      console.log('✅ Code exchange successful. Token received.');

      // Store the SmartHandoff application JWT
      this.authService.setToken(tokenResponse.access_token);

      // Clean up PKCE artefacts — they are single-use only
      sessionStorage.removeItem('pkce_code_verifier');
      sessionStorage.removeItem('oidc_state');

      // Navigate to dashboard or the originally requested URL
      const returnUrl = this.route.snapshot.queryParams['returnUrl'] ?? '/dashboard';
      await this.router.navigateByUrl(returnUrl);
    } catch (err) {
      throw err; // Re-throw to be handled by ngOnInit error handler
    }
  }
}
