import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { environment } from '../../../../environments/environment';

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
 */
@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="login-container" role="main" aria-label="Signing in">
      <p>Redirecting to your hospital's sign-in page…</p>
    </div>
  `,
})
export class LoginComponent implements OnInit {
  async ngOnInit(): Promise<void> {
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

    window.location.href = `${environment.idpBaseUrl}/authorize?${params.toString()}`;
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
