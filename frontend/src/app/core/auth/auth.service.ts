import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';
import { IdleTimeoutService } from './idle-timeout.service';

interface JwtPayload {
  sub: string;
  role: string;
  units: string[];
  email: string;
  jti?: string;   // JWT ID — present on all tokens issued after US-059/TASK-001 deployment
  iat: number;
  exp: number;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/**
 * AuthService — single source of truth for the SmartHandoff session JWT.
 *
 * Security contract (US-056, AC Scenario 4):
 *   - Token is stored ONLY in the private class field `#token`.
 *   - Token is NEVER written to localStorage, sessionStorage, or document.cookie.
 *   - Token is lost on page refresh by design (user must re-authenticate via OIDC).
 *   - getToken() is the only public read accessor; it is used by:
 *       1. JwtInterceptor — adds Authorization: Bearer header to API calls
 *       2. SignalRService — accessTokenFactory for HubConnectionBuilder
 *       3. AuthGuard — checks isAuthenticated() before activating routes
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  // Private class field — NOT a property; inaccessible outside this class.
  // Storing in Angular signal so components can reactively respond to auth state.
  readonly #tokenSignal = signal<string | null>(null);

  /** IdleTimeoutService — wired for 30-minute idle logout (US-059). */
  private readonly idleTimeoutService = inject(IdleTimeoutService);

  /** Reactive auth state for components to consume without exposing the token. */
  readonly isAuthenticated = computed(() => {
    const token = this.#tokenSignal();
    if (!token) return false;
    return !this.#isTokenExpired(token);
  });

  /** Current user claims derived from the JWT payload. Null when not authenticated. */
  readonly currentUser = computed<JwtPayload | null>(() => {
    const token = this.#tokenSignal();
    if (!token || this.#isTokenExpired(token)) return null;
    return this.#decodePayload(token);
  });

  constructor(
    private readonly http: HttpClient,
    private readonly router: Router,
  ) {}

  /**
   * Returns the raw JWT string, or null if not authenticated / token expired.
   *
   * Used by:
   *   - JwtInterceptor: `Authorization: Bearer ${authService.getToken()}`
   *   - SignalRService: `accessTokenFactory: () => authService.getToken() ?? ''`
   */
  getToken(): string | null {
    const token = this.#tokenSignal();
    if (!token || this.#isTokenExpired(token)) return null;
    return token;
  }

  /**
   * Exchange an OIDC id_token for a SmartHandoff application JWT.
   *
   * Called by LoginCallbackComponent after receiving the OIDC code-exchange response.
   * The id_token comes from the IdP after the OIDC authorisation code flow.
   */
  async exchangeIdToken(idToken: string): Promise<void> {
    const response = await firstValueFrom(
      this.http.post<TokenResponse>(`${environment.apiBaseUrl}/api/v1/auth/token`, {
        id_token: idToken,
      })
    );
    this.#setSession(response.access_token);
  }

  /**
   * Store the JWT and start the 30-minute idle timer (US-059).
   * Token is stored ONLY in memory — never in localStorage or cookies.
   */
  #setSession(token: string): void {
    this.#tokenSignal.set(token);
    // Start the 30-minute idle timer — resets on mousemove/keypress/scroll
    this.idleTimeoutService.start(() => {
      this.clearSession();  // discard in-memory JWT on timeout
    });
  }

  /**
   * Clear the in-memory JWT, stop idle monitoring, and redirect to login.
   * Called on session timeout, explicit logout, or 401 response.
   */
  clearSession(): void {
    this.#tokenSignal.set(null);
    this.idleTimeoutService.stop();
    this.router.navigate(['/login']);
  }

  /**
   * User-initiated logout — calls the backend to blocklist the JWT,
   * then clears the local session.
   */
  async logout(): Promise<void> {
    const token = this.getToken();
    if (token) {
      try {
        await firstValueFrom(
          this.http.post(`${environment.apiBaseUrl}/api/v1/auth/logout`, {}, {
            headers: { Authorization: `Bearer ${token}` },
          })
        );
      } catch {
        // Even if the backend call fails, clear the local session
      }
    }
    this.clearSession();
  }

  // ── Private helpers ────────────────────────────────────────────────────────

  #decodePayload(token: string): JwtPayload | null {
    try {
      const base64Payload = token.split('.')[1];
      const decoded = atob(base64Payload.replace(/-/g, '+').replace(/_/g, '/'));
      return JSON.parse(decoded) as JwtPayload;
    } catch {
      return null;
    }
  }

  #isTokenExpired(token: string): boolean {
    const payload = this.#decodePayload(token);
    if (!payload) return true;
    const nowSeconds = Math.floor(Date.now() / 1000);
    // Add 30-second buffer to avoid race conditions near expiry boundary
    return payload.exp < nowSeconds + 30;
  }
}
