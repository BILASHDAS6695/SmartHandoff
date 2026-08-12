import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { Router, ActivatedRoute } from '@angular/router';
import { environment } from '../../../../environments/environment';
import { AuthService } from '../../../core/auth/auth.service';

/**
 * LoginComponent — initiates the OIDC authorisation code + PKCE flow.
 *
 * On init, generates a PKCE code_verifier + code_challenge, stores the
 * verifier in sessionStorage (temporary, for the redirect round-trip only),
 * and redirects the browser to the IdP authorisation endpoint.
 *
 * Note: sessionStorage is used ONLY for the ephemeral PKCE code_verifier.
 * The JWT itself is NEVER stored in sessionStorage (see AuthService).
 *
 * Security: state parameter prevents CSRF; PKCE prevents code interception.
 * 
 * DEV MODE: When environment.devMode is true, shows a dev login form
 * that bypasses OAuth for local development without external IdP.
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="login-container" role="main" aria-label="Sign in">
      <!-- Dev Mode Login Form -->
      @if (isDevMode) {
        <div class="dev-login-card">
          <div class="dev-badge">🔧 DEV MODE</div>
          <h1>SmartHandoff Local Login</h1>
          <p class="dev-warning">OAuth bypassed for local development</p>
          
          <form (ngSubmit)="devLogin()" class="dev-login-form">
            <div class="form-group">
              <label for="email">Email</label>
              <input 
                id="email" 
                type="email" 
                [(ngModel)]="devEmail" 
                name="email"
                placeholder="dev@smarthandoff.local"
                required
              />
            </div>
            
            <div class="form-group">
              <label for="role">Role</label>
              <select id="role" [(ngModel)]="devRole" name="role" required>
                <option value="physician">Physician</option>
                <option value="nurse">Nurse</option>
                <option value="pharmacist">Pharmacist</option>
                <option value="bed_manager">Bed Manager</option>
                <option value="admin">Admin</option>
              </select>
            </div>

            <button type="submit" [disabled]="isLoading" class="dev-login-btn">
              {{ isLoading ? 'Signing in...' : 'Dev Login' }}
            </button>
          </form>

          @if (errorMessage) {
            <div class="error-message">{{ errorMessage }}</div>
          }
          
          <div class="oauth-fallback">
            <button (click)="startOAuthFlow()" class="oauth-btn">
              Use Google OAuth Instead
            </button>
          </div>
        </div>
      } @else {
        <p>Redirecting to your hospital's sign-in page…</p>
      }
    </div>
  `,
  styles: [`
    .login-container {
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      padding: 1rem;
    }
    
    .dev-login-card {
      background: white;
      border-radius: 12px;
      padding: 2rem;
      width: 100%;
      max-width: 400px;
      box-shadow: 0 10px 40px rgba(0,0,0,0.2);
    }
    
    .dev-badge {
      background: #ff9800;
      color: white;
      padding: 0.25rem 0.75rem;
      border-radius: 20px;
      font-size: 0.75rem;
      font-weight: bold;
      display: inline-block;
      margin-bottom: 1rem;
    }
    
    h1 {
      margin: 0 0 0.5rem;
      color: #333;
      font-size: 1.5rem;
    }
    
    .dev-warning {
      color: #666;
      font-size: 0.875rem;
      margin-bottom: 1.5rem;
    }
    
    .dev-login-form {
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    
    .form-group {
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
    }
    
    label {
      font-weight: 500;
      color: #333;
      font-size: 0.875rem;
    }
    
    input, select {
      padding: 0.75rem;
      border: 1px solid #ddd;
      border-radius: 8px;
      font-size: 1rem;
      transition: border-color 0.2s;
    }
    
    input:focus, select:focus {
      outline: none;
      border-color: #667eea;
      box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }
    
    .dev-login-btn {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      border: none;
      padding: 0.875rem;
      border-radius: 8px;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: transform 0.2s, box-shadow 0.2s;
      margin-top: 0.5rem;
    }
    
    .dev-login-btn:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    .dev-login-btn:disabled {
      opacity: 0.7;
      cursor: not-allowed;
    }
    
    .error-message {
      background: #fee2e2;
      color: #dc2626;
      padding: 0.75rem;
      border-radius: 8px;
      margin-top: 1rem;
      font-size: 0.875rem;
    }
    
    .oauth-fallback {
      margin-top: 1.5rem;
      padding-top: 1.5rem;
      border-top: 1px solid #eee;
      text-align: center;
    }
    
    .oauth-btn {
      background: transparent;
      border: 1px solid #ddd;
      padding: 0.625rem 1rem;
      border-radius: 8px;
      cursor: pointer;
      color: #666;
      font-size: 0.875rem;
      transition: background 0.2s;
    }
    
    .oauth-btn:hover {
      background: #f5f5f5;
    }
  `]
})
export class LoginComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly authService = inject(AuthService);

  isDevMode = environment.devMode ?? false;
  devEmail = 'dev@smarthandoff.local';
  devRole = 'physician';
  isLoading = false;
  errorMessage = '';

  async ngOnInit(): Promise<void> {
    // In dev mode, don't auto-redirect to OAuth
    if (this.isDevMode) {
      const params = this.route.snapshot.params;
      if (params['error'] === 'auth_failed' && params['message']) {
        this.errorMessage = params['message'];
      }
      return;
    }
    
    // Production: Start OAuth flow automatically
    await this.startOAuthFlow();
  }

  async devLogin(): Promise<void> {
    this.isLoading = true;
    this.errorMessage = '';

    try {
      const response = await fetch(
        `${environment.apiBaseUrl}/api/v1/auth/dev/test-token?email=${encodeURIComponent(this.devEmail)}&role=${encodeURIComponent(this.devRole)}`,
        { method: 'POST' }
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP ${response.status}`);
      }

      const data = await response.json();

      // Set the token in AuthService
      this.authService.setToken(data.access_token);

      // Persist dev token across reloads for local development only
      // Production tokens are intentionally in-memory only (US-056)
      sessionStorage.setItem('dev_access_token', data.access_token);

      // Navigate to the originally requested route or dashboard
      const returnUrl = this.route.snapshot.queryParams['returnUrl'] || '/dashboard';
      const navigated = await this.router.navigateByUrl(returnUrl);
      if (!navigated) {
        console.error('Dev login: router.navigateByUrl() returned false for', returnUrl);
        this.errorMessage = 'Login succeeded but navigation was blocked.';
      }
    } catch (err) {
      console.error('Dev login failed:', err);
      this.errorMessage = err instanceof Error ? err.message : 'Login failed. Is the backend running?';
    } finally {
      this.isLoading = false;
    }
  }

  async startOAuthFlow(): Promise<void> {
    const { codeVerifier, codeChallenge } = await this.#generatePkce();
    const state = this.#generateState();

    // Store PKCE verifier temporarily for the callback (session-scoped, not auth token)
    sessionStorage.setItem('pkce_code_verifier', codeVerifier);
    sessionStorage.setItem('oidc_state', state);

    const params = new URLSearchParams({
      response_type: 'code',
      client_id: environment.oidcClientId,
      redirect_uri: `${window.location.origin}/auth/callback`,
      scope: 'openid email profile',
      state,
      code_challenge: codeChallenge,
      code_challenge_method: 'S256',
    });

    // Google OAuth 2.0 authorization endpoint
    window.location.href = `${environment.idpBaseUrl}/o/oauth2/v2/auth?${params.toString()}`;
  }

  async #generatePkce(): Promise<{ codeVerifier: string; codeChallenge: string }> {
    const array = new Uint8Array(32);
    crypto.getRandomValues(array);
    const codeVerifier = btoa(String.fromCharCode(...array))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=/g, '');

    const encoder = new TextEncoder();
    const data = encoder.encode(codeVerifier);
    const digest = await crypto.subtle.digest('SHA-256', data);
    const codeChallenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=/g, '');

    return { codeVerifier, codeChallenge };
  }

  #generateState(): string {
    const array = new Uint8Array(16);
    crypto.getRandomValues(array);
    return Array.from(array, (b) => b.toString(16).padStart(2, '0')).join('');
  }
}
