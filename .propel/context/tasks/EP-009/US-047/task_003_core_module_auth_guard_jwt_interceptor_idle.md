---
id: TASK-003
title: "CoreModule — AuthGuard, JwtInterceptor, IdleTimeoutService, ToastService"
user_story: US-047
epic: EP-009
sprint: 2
layer: Frontend / Core
estimate: 4h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, US-056, SEC-001, NFR-034]
---

# TASK-003: CoreModule — AuthGuard, JwtInterceptor, IdleTimeoutService, ToastService

> **Story:** US-047 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Core | **Est:** 4 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task implements the four singleton services that make up the Angular CoreModule: the `AuthGuard` route guard, the `JwtInterceptor` HTTP interceptor, the `IdleTimeoutService` (30-minute idle → logout), and the `ToastService` for system-wide notifications.

Because US-056 (full JWT auth flow) is not yet complete, `AuthGuard` must be implemented with a well-defined interface that accepts an `AuthService` injection token — a stub `AuthService` is provided for integration until US-056 delivers the real implementation.

**JWT scoping rule (US-047 Scenario 4):** The interceptor MUST only attach `Authorization: Bearer` to requests whose URL origin matches `environment.apiOrigin`. CDN, external font, and any non-API URLs must NOT receive the token.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/core/auth/auth.service.stub.ts` | Stub | Minimal `AuthService` stub for development until US-056 |
| `src/app/core/auth/auth.service.token.ts` | Token | `AUTH_SERVICE` injection token |
| `src/app/core/auth/auth.guard.ts` | Guard | `canActivate` functional guard — redirects to `/login` if unauthenticated |
| `src/app/core/auth/jwt.interceptor.ts` | Interceptor | Functional HTTP interceptor — attaches Bearer token to API-origin requests only |
| `src/app/core/auth/idle-timeout.service.ts` | Service | 30-min idle detection → logout; resets on user interaction events |
| `src/app/core/notifications/toast.service.ts` | Service | System-wide snackbar notifications (success, error, warn, info) |
| `src/app/core/notifications/toast.service.spec.ts` | Unit test | Toast service unit tests |
| `src/app/core/auth/jwt.interceptor.spec.ts` | Unit test | Interceptor tests — verifies token attachment and scoping |
| `src/app/core/auth/idle-timeout.service.spec.ts` | Unit test | Idle timeout tests — verifies 30-min trigger and reset on activity |

**Design references:**
- design.md §3.4 — `core/auth/` directory structure
- design.md §8 — Security Architecture: JWT validation, zero-trust perimeter
- US-047 AC Scenario 4 — JWT interceptor scoping to API origin only
- US-047 DoD — `IdleTimeoutService` 30-min idle → logout
- US-047 Technical Notes — `withInterceptors([jwtInterceptor])` functional interceptor API

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | `JwtInterceptor` attaches `Authorization: Bearer` to API-origin requests; skips CDN/external URLs |

---

## Implementation Steps

### 1. Create `AUTH_SERVICE` injection token

```typescript
// src/app/core/auth/auth.service.token.ts
// Injection token decoupling CoreModule from US-056 AuthService implementation.

import { InjectionToken } from '@angular/core';

export interface IAuthService {
  /** Returns the in-memory JWT access token, or null if unauthenticated. */
  getAccessToken(): string | null;
  /** Returns true if the user has a valid, non-expired session. */
  isAuthenticated(): boolean;
  /** Initiates logout — clears token from memory and redirects to /login. */
  logout(): void;
}

export const AUTH_SERVICE = new InjectionToken<IAuthService>('AUTH_SERVICE');
```

### 2. Create `src/app/core/auth/auth.service.stub.ts`

```typescript
// Stub AuthService used until US-056 delivers the real OAuth/JWT implementation.
// Returns a hardcoded development token in non-production environments.
// NEVER deploy this stub to production — it is flagged by the production build check.

import { Injectable } from '@angular/core';
import { environment } from '@env/environment';
import { IAuthService } from './auth.service.token';

@Injectable({ providedIn: 'root' })
export class AuthServiceStub implements IAuthService {
  // In-memory token store — never written to localStorage or sessionStorage.
  // US-056 will replace this with the real token from the OAuth flow.
  private _token: string | null = environment.production
    ? null  // Stub returns null in prod — forces real AuthService registration
    : 'dev-stub-token';

  getAccessToken(): string | null {
    return this._token;
  }

  isAuthenticated(): boolean {
    return this._token !== null;
  }

  logout(): void {
    this._token = null;
    // Real navigation to /login handled by AuthGuard on next route activation
  }
}
```

### 3. Create `src/app/core/auth/auth.guard.ts`

```typescript
// Functional route guard — protects all authenticated routes.
// Redirects unauthenticated users to /login.
// Uses AUTH_SERVICE injection token to remain decoupled from US-056.

import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AUTH_SERVICE } from './auth.service.token';

export const authGuard: CanActivateFn = () => {
  const auth = inject(AUTH_SERVICE);
  const router = inject(Router);

  if (auth.isAuthenticated()) {
    return true;
  }

  // Redirect to login; preserve attempted URL for post-login redirect
  return router.createUrlTree(['/login']);
};
```

### 4. Create `src/app/core/auth/jwt.interceptor.ts`

```typescript
// Functional HTTP interceptor — attaches Authorization: Bearer <token> header.
// SCOPE: Only requests to environment.apiOrigin receive the token.
// Requests to CDN, external fonts, or other origins are passed through unmodified.
//
// Design ref: US-047 AC Scenario 4

import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { environment } from '@env/environment';
import { AUTH_SERVICE } from './auth.service.token';

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AUTH_SERVICE);

  // Only attach token to requests targeting the SmartHandoff API origin.
  // Requests to CDN, Google Fonts, or any other origin pass through unmodified.
  const isApiRequest =
    environment.apiOrigin.length > 0 &&
    req.url.startsWith(environment.apiOrigin);

  const token = auth.getAccessToken();

  if (isApiRequest && token) {
    const authorisedRequest = req.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
    });
    return next(authorisedRequest);
  }

  return next(req);
};
```

### 5. Create `src/app/core/auth/idle-timeout.service.ts`

```typescript
// IdleTimeoutService — monitors user inactivity and logs out after 30 minutes.
// Listens to mousemove, keydown, click, and touchstart events on the window.
// Timer resets on each interaction. Uses RxJS for declarative event handling.
//
// Design ref: US-047 DoD — 30-min idle → logout

import { Injectable, NgZone, OnDestroy, inject } from '@angular/core';
import { fromEvent, merge, Subscription, timer } from 'rxjs';
import { debounceTime, switchMap } from 'rxjs/operators';
import { AUTH_SERVICE } from './auth.service.token';

const IDLE_TIMEOUT_MS = 30 * 60 * 1000; // 30 minutes

const ACTIVITY_EVENTS = ['mousemove', 'keydown', 'click', 'touchstart'] as const;

@Injectable({ providedIn: 'root' })
export class IdleTimeoutService implements OnDestroy {
  private readonly auth = inject(AUTH_SERVICE);
  private readonly ngZone = inject(NgZone);
  private subscription: Subscription | null = null;

  /** Start idle monitoring. Call once after successful authentication. */
  startWatching(): void {
    this.stopWatching(); // clear any existing subscription

    // Run outside Angular zone to avoid triggering change detection on every mouse move
    this.ngZone.runOutsideAngular(() => {
      const activityStream$ = merge(
        ...ACTIVITY_EVENTS.map((event) => fromEvent(window, event)),
      );

      this.subscription = activityStream$
        .pipe(
          debounceTime(300),       // Debounce rapid events — no performance impact
          switchMap(() => timer(IDLE_TIMEOUT_MS)),  // Reset 30-min timer on each activity
        )
        .subscribe(() => {
          // Re-enter Angular zone for logout side effects
          this.ngZone.run(() => {
            this.auth.logout();
          });
        });
    });
  }

  /** Stop idle monitoring. Call on logout or app destruction. */
  stopWatching(): void {
    this.subscription?.unsubscribe();
    this.subscription = null;
  }

  ngOnDestroy(): void {
    this.stopWatching();
  }
}
```

### 6. Create `src/app/core/notifications/toast.service.ts`

```typescript
// ToastService — system-wide snackbar notifications using Angular Material MatSnackBar.
// Provides typed methods: success, error, warn, info.
// Duration defaults: success/info = 3s, warn/error = 6s.

import { Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarConfig } from '@angular/material/snack-bar';

export type ToastType = 'success' | 'error' | 'warn' | 'info';

const DURATION: Record<ToastType, number> = {
  success: 3000,
  info:    3000,
  warn:    6000,
  error:   6000,
};

const PANEL_CLASS: Record<ToastType, string> = {
  success: 'toast-success',
  info:    'toast-info',
  warn:    'toast-warn',
  error:   'toast-error',
};

@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly snackBar = inject(MatSnackBar);

  success(message: string, action = 'Dismiss'): void {
    this.show(message, action, 'success');
  }

  error(message: string, action = 'Dismiss'): void {
    this.show(message, action, 'error');
  }

  warn(message: string, action = 'Dismiss'): void {
    this.show(message, action, 'warn');
  }

  info(message: string, action = 'Dismiss'): void {
    this.show(message, action, 'info');
  }

  private show(message: string, action: string, type: ToastType): void {
    const config: MatSnackBarConfig = {
      duration: DURATION[type],
      panelClass: [PANEL_CLASS[type]],
      horizontalPosition: 'end',
      verticalPosition: 'top',
    };
    this.snackBar.open(message, action, config);
  }
}
```

### 7. Create `src/app/core/auth/jwt.interceptor.spec.ts`

```typescript
import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { jwtInterceptor } from './jwt.interceptor';
import { AUTH_SERVICE, IAuthService } from './auth.service.token';

const mockAuth: IAuthService = {
  getAccessToken: () => 'test-jwt-token',
  isAuthenticated: () => true,
  logout: jest.fn(),
};

describe('jwtInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    // Override environment for test
    jest.mock('@env/environment', () => ({
      environment: { apiOrigin: 'http://localhost:8000', production: false },
    }));

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([jwtInterceptor])),
        provideHttpClientTesting(),
        { provide: AUTH_SERVICE, useValue: mockAuth },
      ],
    });

    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should attach Authorization header to API-origin requests', () => {
    http.get('http://localhost:8000/api/v1/patients').subscribe();
    const req = httpMock.expectOne('http://localhost:8000/api/v1/patients');
    expect(req.request.headers.get('Authorization')).toBe('Bearer test-jwt-token');
    req.flush([]);
  });

  it('should NOT attach Authorization header to CDN requests', () => {
    http.get('https://fonts.googleapis.com/css2?family=Inter').subscribe();
    const req = httpMock.expectOne('https://fonts.googleapis.com/css2?family=Inter');
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush('');
  });

  it('should NOT attach Authorization header to other external origins', () => {
    http.get('https://cdn.example.com/assets/logo.png').subscribe();
    const req = httpMock.expectOne('https://cdn.example.com/assets/logo.png');
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush('');
  });
});
```

### 8. Create `src/app/core/notifications/toast.service.spec.ts`

```typescript
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ToastService } from './toast.service';

describe('ToastService', () => {
  let service: ToastService;
  let snackBarSpy: jest.SpyInstance;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [NoopAnimationsModule],
    });
    service = TestBed.inject(ToastService);
    const snackBar = TestBed.inject(MatSnackBar);
    snackBarSpy = jest.spyOn(snackBar, 'open');
  });

  it('should open snackbar with toast-success panel class', () => {
    service.success('Saved successfully');
    expect(snackBarSpy).toHaveBeenCalledWith(
      'Saved successfully',
      'Dismiss',
      expect.objectContaining({ panelClass: ['toast-success'], duration: 3000 }),
    );
  });

  it('should open snackbar with toast-error panel class and 6s duration', () => {
    service.error('Something went wrong');
    expect(snackBarSpy).toHaveBeenCalledWith(
      'Something went wrong',
      'Dismiss',
      expect.objectContaining({ panelClass: ['toast-error'], duration: 6000 }),
    );
  });
});
```

---

## Validation Script

```bash
# Run CoreModule unit tests
npx jest src/app/core --no-coverage --verbose

# Verify no circular dependencies in core
npx madge --circular src/app/core

# Verify functional interceptor is correctly typed
npx tsc --noEmit

# Verify AUTH_SERVICE token is used — no direct AuthService imports in guard/interceptor
grep -rn "import.*AuthService" src/app/core/auth/auth.guard.ts && echo "FAIL: guard must use token" || echo "Guard uses injection token ✓"
grep -rn "import.*AuthService" src/app/core/auth/jwt.interceptor.ts && echo "FAIL: interceptor must use token" || echo "Interceptor uses injection token ✓"
```

---

## Definition of Done

- [ ] `AUTH_SERVICE` injection token defined; `IAuthService` interface exported
- [ ] `AuthServiceStub` provides a development-only token; returns `null` in production
- [ ] `authGuard` functional guard redirects unauthenticated users to `/login`
- [ ] `jwtInterceptor` attaches `Authorization: Bearer` only to `environment.apiOrigin` requests
- [ ] `jwtInterceptor` does NOT modify requests to CDN, Google Fonts, or external origins (verified by unit tests)
- [ ] `IdleTimeoutService` triggers `auth.logout()` after 30 minutes of inactivity
- [ ] `IdleTimeoutService` resets timer on `mousemove`, `keydown`, `click`, `touchstart`
- [ ] `ToastService` exposes `success()`, `error()`, `warn()`, `info()` with correct durations
- [ ] All unit tests pass (interceptor scoping, toast panel classes, idle timer reset)
- [ ] `npx tsc --noEmit` passes with zero errors
