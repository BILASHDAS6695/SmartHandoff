---
id: TASK-006
title: "Implement Angular `AuthGuard`, `LoginComponent`, and `LoginCallbackComponent`"
user_story: US-056
epic: EP-011
sprint: 1
layer: Frontend
estimate: 3h
priority: Must Have
status: Done
date: 2026-07-22
assignee: Backend Engineer
upstream: [US-056/TASK-005]
---

# TASK-006: Implement Angular `AuthGuard`, `LoginComponent`, and `LoginCallbackComponent`

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Frontend | **Est:** 3 h
> **Status:** Done | **Date:** 2026-07-22

---

## Context

The US-056 DoD specifies three frontend artefacts that complete the OIDC login flow:

1. **`AuthGuard`** — `canActivate()` checks JWT expiry from `AuthService`; redirects to `/login` if expired
2. **`LoginComponent`** — initiates the OIDC authorisation code redirect to the hospital IdP
3. **`LoginCallbackComponent`** — handles the `/auth/callback` redirect from the IdP, reads the `code` query parameter, performs the PKCE code exchange, and calls `AuthService.exchangeIdToken()` with the resulting `id_token`

Design.md Section 8.2 describes the complete staff login flow:
> *"Browser → SSO (OIDC) → MFA → ID Token → Angular → POST /api/v1/auth/token (id_token) → FastAPI → Issue app JWT → Angular stores JWT in memory"*

PKCE (Proof Key for Code Exchange) must be used for the authorisation code flow to prevent CSRF and authorisation code interception attacks (OWASP A05:2021 Security Misconfiguration).

---

## Acceptance Criteria Addressed

| US-056 AC | Requirement |
|---|---|
| **Scenario 1** | Angular login callback component handles OIDC redirect, extracts code, calls token exchange API |
| **Scenario 4** | JWT stored in Angular memory only (AuthService); AuthGuard enforces authentication |
| **DoD** | `AuthGuard`: `canActivate()` checks JWT expiry; redirects to login if expired |
| **DoD** | Angular login callback component: handles OIDC redirect, extracts code, calls token exchange API |

---

## Implementation Steps

### 1. Create `frontend/src/app/core/auth/auth.guard.ts`

```typescript
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * AuthGuard — protects routes that require an authenticated session.
 *
 * Checks AuthService.isAuthenticated() (computed signal that validates
 * JWT expiry). Redirects to /login if no valid token is present.
 *
 * Usage in route config:
 *   {
 *     path: 'dashboard',
 *     canActivate: [authGuard],
 *     loadComponent: () => import('../features/dashboard/dashboard.component')
 *       .then(m => m.DashboardComponent),
 *   }
 */
export const authGuard: CanActivateFn = () => {
  const authService = inject(AuthService);
  const router = inject(Router);

  if (authService.isAuthenticated()) {
    return true;
  }

  // Redirect to login; preserve the attempted URL for post-login redirect
  return router.createUrlTree(['/login'], {
    queryParams: { returnUrl: router.getCurrentNavigation()?.extractedUrl.toString() },
  });
};
```

### 2. Create `frontend/src/app/features/auth/login/login.component.ts`

The login component constructs the OIDC authorisation URL with PKCE and redirects the browser to the IdP:

```typescript
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
```

### 3. Create `frontend/src/app/features/auth/callback/login-callback.component.ts`

```typescript
import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
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
      console.error('OIDC callback error:', err);
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

    // Exchange code for tokens at IdP token endpoint
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: `${window.location.origin}/auth/callback`,
      client_id: environment.oidcClientId,
      code_verifier: codeVerifier,
    });

    const tokenResponse = await firstValueFrom(
      this.http.post<OidcTokenResponse>(
        `${environment.idpBaseUrl}/token`,
        body.toString(),
        { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
      )
    );

    // Exchange OIDC id_token for SmartHandoff app JWT
    await this.authService.exchangeIdToken(tokenResponse.id_token);

    // Clean up PKCE artefacts — they are single-use only
    sessionStorage.removeItem('pkce_code_verifier');
    sessionStorage.removeItem('oidc_state');

    // Navigate to dashboard or the originally requested URL
    const returnUrl = this.route.snapshot.queryParams['returnUrl'] ?? '/dashboard';
    await this.router.navigateByUrl(returnUrl);
  }
}
```

### 4. Add Routes to `frontend/src/app/app.routes.ts`

```typescript
import { Routes } from '@angular/router';
import { authGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login/login.component').then(m => m.LoginComponent),
  },
  {
    path: 'auth/callback',
    loadComponent: () =>
      import('./features/auth/callback/login-callback.component')
        .then(m => m.LoginCallbackComponent),
  },
  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then(m => m.DashboardComponent),
  },
  // Default redirect
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: '**', redirectTo: 'dashboard' },
];
```

### 5. Add OIDC Config to `frontend/src/environments/environment.ts`

```typescript
export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  idpBaseUrl: 'https://idp.hospital.example.com',   // Set in CI/CD env var injection
  oidcClientId: 'smarthandoff-api-gateway',           // Set in CI/CD env var injection
};
```

For `environment.production.ts`:

```typescript
export const environment = {
  production: true,
  apiBaseUrl: '',          // Same origin — served behind Cloud CDN
  idpBaseUrl: '#{IDP_BASE_URL}#',    // Token replaced by Cloud Build substitution
  oidcClientId: '#{OIDC_CLIENT_ID}#',
};
```

---

## Validation

```bash
cd frontend

# 1. TypeScript compilation for auth feature files
npx tsc --noEmit --project tsconfig.json 2>&1 | grep -E "auth|callback|login"
# Expected: no errors

# 2. Confirm PKCE uses Web Crypto API (not Math.random)
grep -rn "crypto\.getRandomValues\|crypto\.subtle" src/app/features/auth/
# Expected: matches in LoginComponent

# 3. Confirm state validation present in callback
grep -n "state mismatch\|State mismatch" src/app/features/auth/callback/login-callback.component.ts
# Expected: one match

# 4. Confirm no JWT in sessionStorage/localStorage (PKCE verifier cleanup)
grep -n "sessionStorage.removeItem" src/app/features/auth/callback/login-callback.component.ts
# Expected: two matches (pkce_code_verifier and oidc_state)
```

---

## Files Touched

| File | Action |
|---|---|
| `frontend/src/app/core/auth/auth.guard.ts` | Create |
| `frontend/src/app/features/auth/login/login.component.ts` | Create |
| `frontend/src/app/features/auth/callback/login-callback.component.ts` | Create |
| `frontend/src/app/app.routes.ts` | Add `/login`, `/auth/callback`, `/dashboard` routes |
| `frontend/src/environments/environment.ts` | Add `idpBaseUrl`, `oidcClientId` |
| `frontend/src/environments/environment.production.ts` | Add token placeholders for CI substitution |

---

## Definition of Done Checklist

- [ ] `authGuard` implemented as `CanActivateFn`; redirects to `/login` with `returnUrl` when unauthenticated
- [ ] `LoginComponent` initiates PKCE `S256` flow; uses `crypto.getRandomValues()` for code_verifier and state
- [ ] `LoginCallbackComponent` validates state parameter (CSRF protection) before proceeding
- [ ] PKCE `code_verifier` and `oidc_state` removed from `sessionStorage` after use (both success and failure paths)
- [ ] `LoginCallbackComponent` calls `authService.exchangeIdToken()` with `id_token` (not `access_token`)
- [ ] Routes registered: `/login`, `/auth/callback`, `/dashboard` (guarded)
- [ ] `idpBaseUrl` and `oidcClientId` in environment files; production values use CI substitution tokens
- [ ] TypeScript compiles with no errors in all new auth files

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-056/TASK-005 | Upstream task | `AuthService.exchangeIdToken()` and `isAuthenticated` must exist before AuthGuard and Callback can use them |
