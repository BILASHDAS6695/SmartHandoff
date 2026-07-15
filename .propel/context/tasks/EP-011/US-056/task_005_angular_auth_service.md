---
id: TASK-005
title: "Implement Angular `AuthService` with In-Memory JWT Storage and SignalR Token Factory"
user_story: US-056
epic: EP-011
sprint: 1
layer: Frontend
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-15
assignee: Backend Engineer
upstream: [US-056/TASK-004]
---

# TASK-005: Implement Angular `AuthService` with In-Memory JWT Storage and SignalR Token Factory

> **Story:** US-056 | **Epic:** EP-011 | **Sprint:** 1 | **Layer:** Frontend | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-15

---

## Context

AC Scenario 4 explicitly mandates: *"No JWT token is found in `localStorage`, `sessionStorage`, or `document.cookie`; the token is only in Angular's `AuthService` memory."*

This is a direct HIPAA access control measure — XSS attacks cannot exfiltrate JWTs from browser storage if the token is stored only in a JavaScript class field. The design.md Section 8.2 confirms: *"Angular stores JWT in memory (NOT localStorage — XSS protection)"*.

The Technical Notes additionally specify: `HubConnectionBuilder.withUrl(url, {accessTokenFactory: () => authService.getToken()})` — meaning `AuthService.getToken()` is the single interface used by both the HTTP interceptor and the SignalR hub.

This task implements `AuthService` as a singleton injectable in Angular's root injector (`providedIn: 'root'`).

---

## Acceptance Criteria Addressed

| US-056 AC | Requirement |
|---|---|
| **Scenario 1** | JWT stored in Angular memory after successful login |
| **Scenario 4** | No JWT in `localStorage`, `sessionStorage`, or `document.cookie` |
| **DoD** | Angular `AuthService`: stores JWT in private class field; exposes `getToken()` method |

---

## Implementation Steps

### 1. Create `frontend/src/app/core/auth/auth.service.ts`

```typescript
import { Injectable, signal, computed } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';
import { environment } from '../../../environments/environment';

interface JwtPayload {
  sub: string;
  role: string;
  units: string[];
  email: string;
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
    // Store ONLY in memory — never in localStorage or cookies
    this.#tokenSignal.set(response.access_token);
  }

  /**
   * Clear the in-memory JWT and redirect to login.
   * Called on session timeout, explicit logout, or 401 response.
   */
  logout(): void {
    this.#tokenSignal.set(null);
    this.router.navigate(['/login']);
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
```

### 2. Create `frontend/src/app/core/auth/jwt.interceptor.ts`

The interceptor attaches the Bearer token to every outbound API request:

```typescript
import { HttpInterceptorFn, HttpRequest, HttpHandlerFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';

/**
 * JwtInterceptor — attaches Authorization: Bearer header to API requests.
 *
 * Only attaches the token to requests targeting the configured API base URL.
 * This prevents the JWT from being sent to third-party URLs (e.g. RxNav API).
 */
export const jwtInterceptor: HttpInterceptorFn = (
  req: HttpRequest<unknown>,
  next: HttpHandlerFn,
) => {
  const authService = inject(AuthService);
  const token = authService.getToken();

  if (token && req.url.startsWith('/api')) {
    const authReq = req.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    });
    return next(authReq);
  }

  return next(req);
};
```

### 3. Register the HTTP Interceptor in `frontend/src/app/app.config.ts`

```typescript
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { jwtInterceptor } from './core/auth/jwt.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    // ... existing providers
    provideHttpClient(withInterceptors([jwtInterceptor])),
  ],
};
```

### 4. Confirm SignalR Hub Integration Pattern

In `frontend/src/app/core/signalr/signalr.service.ts` (created in the SignalR story), ensure the hub connection uses `accessTokenFactory` pointing to `AuthService.getToken()`:

```typescript
// Confirm this pattern exists in the SignalR service — do NOT duplicate it.
// Per US-056 Technical Notes:
//   HubConnectionBuilder.withUrl(url, { accessTokenFactory: () => authService.getToken() })

this.connection = new HubConnectionBuilder()
  .withUrl(`${environment.apiBaseUrl}/hubs/dashboard`, {
    accessTokenFactory: () => this.authService.getToken() ?? '',
  })
  .withAutomaticReconnect()
  .build();
```

If the SignalR service does not yet exist, add a `TODO(US-056)` comment in `signalr.service.ts` to add this pattern when it is implemented.

---

## Validation

```bash
cd frontend

# Confirm TypeScript compiles without errors in auth files
npx tsc --noEmit --project tsconfig.json 2>&1 | grep "core/auth"
# Expected: no errors

# Confirm no localStorage/sessionStorage writes in auth files
grep -rn "localStorage\|sessionStorage\|document\.cookie" src/app/core/auth/
# Expected: no matches
```

---

## Files Touched

| File | Action |
|---|---|
| `frontend/src/app/core/auth/auth.service.ts` | Create |
| `frontend/src/app/core/auth/jwt.interceptor.ts` | Create |
| `frontend/src/app/app.config.ts` | Register `jwtInterceptor` in `provideHttpClient` |
| `frontend/src/app/core/signalr/signalr.service.ts` | Confirm/add `accessTokenFactory` pattern |

---

## Definition of Done Checklist

- [ ] `AuthService` injectable in root injector (`providedIn: 'root'`)
- [ ] JWT stored in private class field using Angular signal (`#tokenSignal`)
- [ ] `getToken()` returns `null` for expired tokens (30-second buffer applied)
- [ ] `isAuthenticated` is a `computed()` signal (reactive, not a method)
- [ ] `currentUser` is a `computed()` signal returning decoded `JwtPayload | null`
- [ ] `logout()` clears the token and navigates to `/login`
- [ ] `jwtInterceptor` only attaches token to requests starting with `/api`
- [ ] `jwtInterceptor` registered in `app.config.ts`
- [ ] Zero references to `localStorage`, `sessionStorage`, or `document.cookie` in `src/app/core/auth/`
- [ ] `accessTokenFactory` pattern confirmed in SignalR service

---

## Dependencies

| Dependency | Type | Notes |
|---|---|---|
| US-056/TASK-004 | Upstream task | `POST /api/v1/auth/token` endpoint must exist before `exchangeIdToken()` can be called |
