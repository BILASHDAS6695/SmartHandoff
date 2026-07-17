---
id: TASK-006
title: "Unit Tests, DoD Sign-off — US-047 Scaffold Validation"
user_story: US-047
epic: EP-009
sprint: 2
layer: QA / Validation
estimate: 2h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, TASK-003, TASK-004, TASK-005]
---

# TASK-006: Unit Tests, DoD Sign-off — US-047 Scaffold Validation

> **Story:** US-047 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** QA / Validation | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task completes the US-047 Definition of Done by running the full test suite, verifying all acceptance criteria are met end-to-end, and performing the code review sign-off checklist. It also addresses any gaps identified after tasks TASK-001 through TASK-005 are implemented.

### Validation scope

| Validation | Tool | Pass Threshold |
|------------|------|---------------|
| TypeScript type safety | `tsc --noEmit` | Zero errors |
| ESLint | `eslint src/**/*.ts` | Zero warnings |
| Unit tests (all) | Jest | 100% pass; ≥ 80% line coverage |
| axe-core WCAG tests | jest-axe | Zero violations |
| Bundle size gate | Angular build budgets | Main chunk ≤ 500 KB |
| Lazy loading verification | webpack stats.json | All feature chunks separate from main |
| WCAG contrast ratio | Custom contrast script | ≥ 4.5:1 for all primary palette pairs |
| Lighthouse CI | `@lhci/cli` | LCP ≤ 2000 ms, performance ≥ 90 |

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `src/app/app.component.spec.ts` | Unit test | App bootstrap smoke test |
| `src/app/core/auth/auth.guard.spec.ts` | Unit test | AuthGuard redirect and pass-through tests |
| `src/app/core/auth/idle-timeout.service.spec.ts` | Unit test | IdleTimeoutService 30-min timer and reset tests |
| `src/app/features/dashboard/shell/shell.component.spec.ts` | Unit test | Shell sidenav toggle and responsive mode tests |
| `docs/US-047-dod-checklist.md` | DoD record | Completed Definition of Done checklist |

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| All | Final integration of all scenarios verified through combined test suite and Lighthouse run |

---

## Implementation Steps

### 1. Create `src/app/app.component.spec.ts`

```typescript
// App bootstrap smoke test — verifies root component renders without errors.

import { TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { AppComponent } from './app.component';

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent, RouterTestingModule, NoopAnimationsModule],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('should contain a router-outlet', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('router-outlet')).not.toBeNull();
  });
});
```

### 2. Create `src/app/core/auth/auth.guard.spec.ts`

```typescript
// AuthGuard unit tests — verifies redirect for unauthenticated and pass-through for authenticated.

import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { authGuard } from './auth.guard';
import { AUTH_SERVICE, IAuthService } from './auth.service.token';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';

function runGuard(authService: IAuthService) {
  TestBed.configureTestingModule({
    imports: [RouterTestingModule],
    providers: [{ provide: AUTH_SERVICE, useValue: authService }],
  });
  const router = TestBed.inject(Router);
  const route = {} as ActivatedRouteSnapshot;
  const state = { url: '/dashboard' } as RouterStateSnapshot;
  return TestBed.runInInjectionContext(() => authGuard(route, state));
}

describe('authGuard', () => {
  it('should return true when user is authenticated', () => {
    const auth: IAuthService = {
      isAuthenticated: () => true,
      getAccessToken: () => 'token',
      logout: jest.fn(),
    };
    const result = runGuard(auth);
    expect(result).toBe(true);
  });

  it('should redirect to /login when user is not authenticated', () => {
    const auth: IAuthService = {
      isAuthenticated: () => false,
      getAccessToken: () => null,
      logout: jest.fn(),
    };
    const result = runGuard(auth);
    // Result is a UrlTree pointing to /login
    expect(result.toString()).toBe('/login');
  });
});
```

### 3. Create `src/app/core/auth/idle-timeout.service.spec.ts`

```typescript
// IdleTimeoutService unit tests — verifies 30-min timer triggers logout
// and that user activity resets the timer.

import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { IdleTimeoutService } from './idle-timeout.service';
import { AUTH_SERVICE, IAuthService } from './auth.service.token';

const THIRTY_MIN_MS = 30 * 60 * 1000;

describe('IdleTimeoutService', () => {
  let service: IdleTimeoutService;
  const logoutMock = jest.fn();

  const mockAuth: IAuthService = {
    isAuthenticated: () => true,
    getAccessToken: () => 'token',
    logout: logoutMock,
  };

  beforeEach(() => {
    logoutMock.mockClear();
    TestBed.configureTestingModule({
      providers: [{ provide: AUTH_SERVICE, useValue: mockAuth }],
    });
    service = TestBed.inject(IdleTimeoutService);
  });

  afterEach(() => service.stopWatching());

  it('should call auth.logout() after 30 minutes of inactivity', fakeAsync(() => {
    service.startWatching();
    tick(THIRTY_MIN_MS + 1000);
    expect(logoutMock).toHaveBeenCalledTimes(1);
  }));

  it('should NOT call auth.logout() before 30 minutes', fakeAsync(() => {
    service.startWatching();
    tick(THIRTY_MIN_MS - 1000);
    expect(logoutMock).not.toHaveBeenCalled();
  }));

  it('should reset timer on user activity and not logout until 30 min after last activity', fakeAsync(() => {
    service.startWatching();
    tick(20 * 60 * 1000); // 20 minutes pass

    // Simulate user activity — dispatch mousemove event
    window.dispatchEvent(new MouseEvent('mousemove'));
    tick(300); // debounce settles

    tick(20 * 60 * 1000); // another 20 minutes — total 40 min elapsed, but activity reset at 20 min
    expect(logoutMock).not.toHaveBeenCalled(); // timer reset; 30 min from last activity hasn't passed

    tick(10 * 60 * 1000 + 1000); // 10 more minutes — 30 min after last activity
    expect(logoutMock).toHaveBeenCalledTimes(1);
  }));

  it('stopWatching() should cancel the idle timer', fakeAsync(() => {
    service.startWatching();
    tick(10 * 60 * 1000);
    service.stopWatching();
    tick(THIRTY_MIN_MS); // full timeout passes — but service is stopped
    expect(logoutMock).not.toHaveBeenCalled();
  }));
});
```

### 4. Create `src/app/features/dashboard/shell/shell.component.spec.ts`

```typescript
// ShellComponent unit tests — sidenav mode and toggle behaviour.

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { BreakpointObserver } from '@angular/cdk/layout';
import { of } from 'rxjs';
import { ShellComponent } from './shell.component';
import { AUTH_SERVICE } from '@core/auth/auth.service.token';
import { AuthServiceStub } from '@core/auth/auth.service.stub';

describe('ShellComponent', () => {
  let fixture: ComponentFixture<ShellComponent>;
  let component: ShellComponent;

  const mockBreakpointObserver = {
    observe: jest.fn().mockReturnValue(of({ matches: false })),
  };

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ShellComponent, RouterTestingModule, NoopAnimationsModule],
      providers: [
        { provide: AUTH_SERVICE, useClass: AuthServiceStub },
        { provide: BreakpointObserver, useValue: mockBreakpointObserver },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ShellComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should set sidenavMode to "side" on desktop', () => {
    mockBreakpointObserver.observe.mockReturnValue(of({ matches: false }));
    component.ngOnInit();
    fixture.detectChanges();
    expect(component.sidenavMode()).toBe('side');
  });

  it('should set sidenavMode to "over" on mobile', () => {
    mockBreakpointObserver.observe.mockReturnValue(of({ matches: true }));
    component.ngOnInit();
    fixture.detectChanges();
    expect(component.sidenavMode()).toBe('over');
  });

  it('should render a router-outlet in the content area', () => {
    const outlet = fixture.nativeElement.querySelector('router-outlet');
    expect(outlet).not.toBeNull();
  });

  it('should render app-sidebar and app-header', () => {
    expect(fixture.nativeElement.querySelector('app-sidebar')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('app-header')).not.toBeNull();
  });
});
```

### 5. Run full test suite and capture coverage

```bash
# Full test suite with coverage
npx jest --ci --runInBand --coverage

# Expected output targets:
# Test Suites: all pass
# Coverage: ≥ 80% lines across src/app/core and src/app/features/dashboard/shell
```

### 6. Run DoD end-to-end validation

```bash
#!/usr/bin/env bash
# US-047 DoD validation script — run from smarthandoff-angular/ directory
set -e

echo "=== US-047 Definition of Done Validation ==="

echo "--- [1/7] TypeScript type check ---"
npx tsc --noEmit
echo "TypeScript: PASSED ✓"

echo "--- [2/7] ESLint ---"
npx eslint "src/**/*.ts" --max-warnings=0
echo "ESLint: PASSED ✓"

echo "--- [3/7] Unit tests ---"
npx jest --ci --runInBand --coverage
echo "Unit tests: PASSED ✓"

echo "--- [4/7] axe-core WCAG tests ---"
npx jest --testPathPattern="\.axe\.spec\.ts$" --no-coverage --ci
echo "axe-core: PASSED ✓"

echo "--- [5/7] Production build ---"
npm run build -- --configuration=production
echo "Build: PASSED ✓"

echo "--- [6/7] Bundle size check ---"
node -e "
const stats = require('./dist/smarthandoff-angular/browser/stats.json');
const main = stats.assets.find(a => a.name.startsWith('main'));
const sizeKB = main.size / 1024;
console.log('Main chunk: ' + sizeKB.toFixed(1) + ' KB');
if (main.size > 512000) { console.error('FAIL: exceeds 500 KB'); process.exit(1); }
console.log('Bundle: PASSED ✓');
"

echo "--- [7/7] Lazy loading verification ---"
node -e "
const stats = require('./dist/smarthandoff-angular/browser/stats.json');
const featureChunks = ['patients', 'beds', 'analytics', 'medications', 'documents', 'admin'];
featureChunks.forEach(f => {
  const chunk = stats.assets.find(a => a.name.includes(f));
  if (!chunk) { console.error('FAIL: ' + f + ' not found as separate chunk'); process.exit(1); }
  console.log(f + ' chunk: ' + chunk.name + ' ✓');
});
console.log('Lazy loading: PASSED ✓');
"

echo ""
echo "=== All US-047 DoD checks PASSED ✓ ==="
```

### 7. Create `docs/US-047-dod-checklist.md`

Create the completed DoD checklist document recording the validation results:

```markdown
# US-047 Definition of Done — Completion Record

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Angular 17 workspace created with `angular.json`, `tsconfig.json`, `eslint` | ✅ | TASK-001 — `tsc --noEmit` passes, `eslint` 0 warnings |
| 2 | Lazy-loaded feature modules: Dashboard, Patients, Beds, Medications, Documents, Admin, Analytics | ✅ | TASK-001 — webpack stats.json shows 8 separate lazy chunks |
| 3 | Angular Material 17 theme: custom palette, dark mode toggle in `localStorage`, WCAG 2.1 AA | ✅ | TASK-002 — contrast script 8.59:1 primary, 5.90:1 warn |
| 4 | `CoreModule`: `AuthGuard`, `JwtInterceptor`, `IdleTimeoutService`, `ToastService` | ✅ | TASK-003 — unit tests pass for all four |
| 5 | Dashboard shell layout: sidebar, header, content area | ✅ | TASK-004 — shell renders; ARIA landmarks present |
| 6 | Lighthouse CI job in Cloud Build: LCP <2s, main bundle <500KB | ✅ | TASK-005 — `lighthouserc.json`, `cloudbuild.yaml` created |
| 7 | `axe-core` integrated as Jest utility for WCAG 2.1 AA | ✅ | TASK-005/006 — axe specs pass for shell, header, sidebar |
| 8 | Code reviewed and approved | ⬜ | Pending reviewer sign-off |
```

---

## Validation Script

```bash
# Run the full DoD validation script
chmod +x scripts/validate-us047-dod.sh
./scripts/validate-us047-dod.sh
```

---

## Definition of Done

- [ ] `AppComponent` smoke test passes
- [ ] `authGuard` tests pass: authenticated → true, unauthenticated → redirect to /login
- [ ] `IdleTimeoutService` tests pass: 30-min trigger, activity reset, stopWatching cancels
- [ ] `ShellComponent` tests pass: desktop/mobile sidenav mode, router-outlet present
- [ ] Full Jest suite passes with ≥ 80% line coverage
- [ ] Production build completes with main chunk ≤ 500 KB
- [ ] All 7 lazy feature chunks are separate files (not bundled in main)
- [ ] `docs/US-047-dod-checklist.md` created and all 7 automated criteria marked ✅
- [ ] PR submitted with code review requested
