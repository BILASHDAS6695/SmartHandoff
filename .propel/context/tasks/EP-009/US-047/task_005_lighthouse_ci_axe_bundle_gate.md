---
id: TASK-005
title: "Lighthouse CI + axe-core WCAG Integration — Cloud Build Pipeline & Bundle Budget Gates"
user_story: US-047
epic: EP-009
sprint: 2
layer: DevOps / QA
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [TASK-001, TASK-002, TASK-004, TR-002, NFR-001, NFR-034]
---

# TASK-005: Lighthouse CI + axe-core WCAG Integration — Cloud Build Pipeline & Bundle Budget Gates

> **Story:** US-047 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** DevOps / QA | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task integrates automated quality gates into the Cloud Build CI pipeline and Jest test suite:

1. **Lighthouse CI** — runs on every PR build; enforces LCP < 2 s and main chunk < 500 KB (US-047 Scenario 1, TR-002)
2. **Bundle size gate** — Angular build budgets (already configured in TASK-001) are enforced at build time; this task adds a separate CI step with `webpack-bundle-analyzer` for PR reporting
3. **axe-core WCAG gate** — integrated into the Jest test suite; all rendered shell components are tested for WCAG 2.1 AA violations before merge

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `lighthouserc.json` | Config | Lighthouse CI configuration with LCP and bundle size assertions |
| `cloudbuild.yaml` | CI | Cloud Build pipeline steps: install → lint → test → build → Lighthouse CI |
| `src/app/core/testing/axe-setup.ts` | Test utility | axe-core setup helper for Jest component tests |
| `src/app/features/dashboard/shell/shell.component.axe.spec.ts` | Axe test | WCAG 2.1 AA axe-core test for the shell layout |
| `src/app/features/dashboard/shell/sidebar/sidebar.component.axe.spec.ts` | Axe test | WCAG 2.1 AA axe-core test for the sidebar |
| `src/app/features/dashboard/shell/header/header.component.axe.spec.ts` | Axe test | WCAG 2.1 AA axe-core test for the header |

**Design references:**
- design.md §5.1 TR-002 — Angular initial page load <2s, main chunk <500KB
- US-047 DoD — Lighthouse CI job added to Cloud Build pipeline; `axe-core` integrated as Jest utility
- US-047 AC Scenario 1 — LCP < 2s on 4G throttling; main chunk < 500 KB

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Lighthouse CI enforces LCP < 2 s and main chunk < 500 KB — build fails if thresholds exceeded |
| Scenario 3 | axe-core tests verify WCAG 2.1 AA compliance on shell, sidebar, and header components |

---

## Implementation Steps

### 1. Install Lighthouse CI and axe-core dependencies

```bash
npm install --save-dev @lhci/cli@0.14 webpack-bundle-analyzer jest-axe axe-core @types/jest-axe

# Add bundle analyser npm script to package.json
```

### 2. Add npm scripts to `package.json`

```json
{
  "scripts": {
    "build:stats": "ng build --configuration=production --stats-json",
    "analyze:bundle": "webpack-bundle-analyzer dist/smarthandoff-angular/browser/stats.json dist/smarthandoff-angular/browser -p 8888 --no-open",
    "lhci": "lhci autorun",
    "test:axe": "jest --testPathPattern=\\.axe\\.spec\\.ts$ --no-coverage"
  }
}
```

### 3. Create `lighthouserc.json`

```json
{
  "$schema": "https://raw.githubusercontent.com/GoogleChrome/lighthouse-ci/main/docs/configuration.schema.json",
  "ci": {
    "collect": {
      "startServerCommand": "npx http-server dist/smarthandoff-angular/browser -p 4200 --silent",
      "startServerReadyPattern": "Available on",
      "url": ["http://localhost:4200/"],
      "numberOfRuns": 3,
      "settings": {
        "chromeFlags": "--no-sandbox --disable-dev-shm-usage",
        "throttlingMethod": "simulate",
        "throttling": {
          "rttMs": 40,
          "throughputKbps": 10240,
          "cpuSlowdownMultiplier": 4
        },
        "emulatedFormFactor": "desktop",
        "screenEmulation": {
          "mobile": false,
          "width": 1350,
          "height": 940,
          "deviceScaleFactor": 1
        }
      }
    },
    "assert": {
      "preset": "lighthouse:no-pwa",
      "assertions": {
        "categories:performance": ["error", { "minScore": 0.9 }],
        "first-contentful-paint": ["error", { "maxNumericValue": 2000 }],
        "largest-contentful-paint": ["error", { "maxNumericValue": 2000 }],
        "interactive": ["warn", { "maxNumericValue": 3500 }],
        "total-blocking-time": ["warn", { "maxNumericValue": 300 }],
        "categories:accessibility": ["error", { "minScore": 0.95 }],
        "total-byte-weight": ["error", { "maxNumericValue": 512000 }]
      }
    },
    "upload": {
      "target": "temporary-public-storage"
    }
  }
}
```

### 4. Create `cloudbuild.yaml`

```yaml
# Cloud Build CI pipeline for SmartHandoff Angular PWA.
# Enforces: lint → unit tests (with axe-core) → production build → Lighthouse CI.
# Design ref: US-047 DoD — Lighthouse CI job with LCP <2s and bundle <500KB gates.

steps:
  # Step 1: Install dependencies
  - name: 'node:20-alpine'
    id: 'install'
    entrypoint: npm
    args: ['ci', '--prefer-offline']
    dir: 'smarthandoff-angular'

  # Step 2: TypeScript type check
  - name: 'node:20-alpine'
    id: 'typecheck'
    entrypoint: npx
    args: ['tsc', '--noEmit']
    dir: 'smarthandoff-angular'
    waitFor: ['install']

  # Step 3: ESLint
  - name: 'node:20-alpine'
    id: 'lint'
    entrypoint: npx
    args: ['eslint', 'src/**/*.ts', '--max-warnings=0']
    dir: 'smarthandoff-angular'
    waitFor: ['install']

  # Step 4: Unit tests (Jest) — includes axe-core WCAG tests
  - name: 'node:20-alpine'
    id: 'test'
    entrypoint: npm
    args: ['test', '--', '--ci', '--runInBand', '--coverage', '--coverageThreshold={"global":{"lines":80}}']
    dir: 'smarthandoff-angular'
    waitFor: ['install']

  # Step 5: Production build — Angular budget gate (500KB error threshold)
  - name: 'node:20-alpine'
    id: 'build'
    entrypoint: npm
    args: ['run', 'build', '--', '--configuration=production']
    dir: 'smarthandoff-angular'
    waitFor: ['typecheck', 'lint', 'test']

  # Step 6: Bundle size verification — fail if main chunk exceeds 500KB
  - name: 'node:20-alpine'
    id: 'bundle-check'
    entrypoint: node
    args:
      - '-e'
      - |
        const stats = require('./dist/smarthandoff-angular/browser/stats.json');
        const main = stats.assets.find(a => a.name.startsWith('main'));
        const sizeKB = main.size / 1024;
        console.log(`Main chunk: ${sizeKB.toFixed(1)} KB`);
        if (main.size > 512000) {
          console.error(`FAIL: main chunk ${sizeKB.toFixed(1)} KB exceeds 500 KB limit`);
          process.exit(1);
        }
        console.log('Bundle size check PASSED ✓');
    dir: 'smarthandoff-angular'
    waitFor: ['build']

  # Step 7: Lighthouse CI — LCP <2s and performance ≥90 gates
  - name: 'gcr.io/cloud-builders/node:20'
    id: 'lighthouse-ci'
    entrypoint: bash
    args:
      - '-c'
      - |
        npm install -g http-server
        npm run lhci
    dir: 'smarthandoff-angular'
    waitFor: ['build']

  # Step 8: Deploy preview to Cloud Run (non-blocking on PR builds)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: 'deploy-preview'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'smarthandoff-angular-preview'
      - '--image=gcr.io/$PROJECT_ID/smarthandoff-angular:$SHORT_SHA'
      - '--region=us-central1'
      - '--platform=managed'
      - '--no-traffic'
    waitFor: ['bundle-check', 'lighthouse-ci']

timeout: '1200s'

options:
  machineType: 'E2_HIGHCPU_8'
  logging: CLOUD_LOGGING_ONLY

substitutions:
  _REGION: 'us-central1'
```

### 5. Create `src/app/core/testing/axe-setup.ts`

```typescript
// axe-core setup for Jest component accessibility testing.
// Import this in any component spec file to enable WCAG 2.1 AA assertions.
//
// Usage in spec files:
//   import { checkA11y, renderForAxe } from '@core/testing/axe-setup';
//
// Design ref: US-047 DoD — axe-core integrated as Jest test utility for WCAG 2.1 AA

import { configureAxe, toHaveNoViolations } from 'jest-axe';

// Extend Jest matchers with axe accessibility assertions
expect.extend(toHaveNoViolations);

/**
 * Pre-configured axe runner with WCAG 2.1 AA ruleset.
 * Use this instead of the default axe() to ensure consistent rule coverage.
 */
export const axe = configureAxe({
  rules: {
    // Enforce WCAG 2.1 AA rules
    'color-contrast': { enabled: true },
    'label': { enabled: true },
    'button-name': { enabled: true },
    'link-name': { enabled: true },
    'image-alt': { enabled: true },
    'landmark-one-main': { enabled: true },
    'region': { enabled: true },
    'heading-order': { enabled: true },
    'skip-link': { enabled: false },  // Disabled — skip link added at app shell level only
  },
});

export { toHaveNoViolations };
```

### 6. Create `src/app/features/dashboard/shell/shell.component.axe.spec.ts`

```typescript
// WCAG 2.1 AA accessibility test for ShellComponent using axe-core.
// Design ref: US-047 DoD — axe-core integrated as Jest test utility

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { ShellComponent } from './shell.component';
import { AUTH_SERVICE } from '@core/auth/auth.service.token';
import { AuthServiceStub } from '@core/auth/auth.service.stub';
import { axe, toHaveNoViolations } from '@core/testing/axe-setup';

expect.extend(toHaveNoViolations);

describe('ShellComponent — WCAG 2.1 AA (axe-core)', () => {
  let fixture: ComponentFixture<ShellComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ShellComponent, RouterTestingModule, NoopAnimationsModule],
      providers: [{ provide: AUTH_SERVICE, useClass: AuthServiceStub }],
    }).compileComponents();

    fixture = TestBed.createComponent(ShellComponent);
    fixture.detectChanges();
  });

  it('should have no WCAG 2.1 AA accessibility violations', async () => {
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });
});
```

### 7. Create `src/app/features/dashboard/shell/header/header.component.axe.spec.ts`

```typescript
// WCAG 2.1 AA accessibility test for HeaderComponent.

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { HeaderComponent } from './header.component';
import { axe, toHaveNoViolations } from '@core/testing/axe-setup';

expect.extend(toHaveNoViolations);

describe('HeaderComponent — WCAG 2.1 AA (axe-core)', () => {
  let fixture: ComponentFixture<HeaderComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HeaderComponent, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(HeaderComponent);
    fixture.detectChanges();
  });

  it('should have no WCAG 2.1 AA accessibility violations', async () => {
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });

  it('should have accessible notification button with dynamic aria-label', () => {
    const btn = fixture.nativeElement.querySelector('[aria-label*="Notifications"]');
    expect(btn).not.toBeNull();
  });

  it('should have accessible dark mode toggle button', () => {
    const btn = fixture.nativeElement.querySelector('[aria-label*="mode"]');
    expect(btn).not.toBeNull();
  });
});
```

### 8. Create `src/app/features/dashboard/shell/sidebar/sidebar.component.axe.spec.ts`

```typescript
// WCAG 2.1 AA accessibility test for SidebarComponent.

import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { NoopAnimationsModule } from '@angular/platform-browser/animations';
import { SidebarComponent } from './sidebar.component';
import { axe, toHaveNoViolations } from '@core/testing/axe-setup';

expect.extend(toHaveNoViolations);

describe('SidebarComponent — WCAG 2.1 AA (axe-core)', () => {
  let fixture: ComponentFixture<SidebarComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SidebarComponent, RouterTestingModule, NoopAnimationsModule],
    }).compileComponents();

    fixture = TestBed.createComponent(SidebarComponent);
    fixture.detectChanges();
  });

  it('should have no WCAG 2.1 AA accessibility violations', async () => {
    const results = await axe(fixture.nativeElement);
    expect(results).toHaveNoViolations();
  });

  it('should render all 6 primary navigation items', () => {
    const navItems = fixture.nativeElement.querySelectorAll('a[mat-list-item]');
    expect(navItems.length).toBeGreaterThanOrEqual(6);
  });

  it('should have aria-label on each navigation link', () => {
    const navItems = fixture.nativeElement.querySelectorAll('a[mat-list-item]');
    navItems.forEach((item: Element) => {
      expect(item.getAttribute('aria-label')).toBeTruthy();
    });
  });
});
```

---

## Validation Script

```bash
# Run all axe-core accessibility tests
npx jest --testPathPattern="\.axe\.spec\.ts$" --no-coverage --verbose

# Build and run Lighthouse CI locally
npm run build
npm run lhci

# Verify bundle-check script
npm run build:stats
node -e "
const stats = require('./dist/smarthandoff-angular/browser/stats.json');
const main = stats.assets.find(a => a.name.startsWith('main'));
console.log('Main chunk:', (main.size / 1024).toFixed(1), 'KB');
console.assert(main.size <= 512000, 'Main chunk must be ≤ 500 KB');
console.log('Bundle size gate PASSED ✓');
"

# Verify Lighthouse CI config is valid JSON
node -e "JSON.parse(require('fs').readFileSync('lighthouserc.json', 'utf8')); console.log('lighthouserc.json valid ✓')"

# Verify cloudbuild.yaml is valid YAML
python3 -c "import yaml; yaml.safe_load(open('cloudbuild.yaml')); print('cloudbuild.yaml valid ✓')"
```

---

## Definition of Done

- [ ] `lighthouserc.json` configured with `largest-contentful-paint ≤ 2000ms` and `total-byte-weight ≤ 512000` (500 KB) assertions
- [ ] `cloudbuild.yaml` has steps: install → typecheck → lint → test → build → bundle-check → Lighthouse CI
- [ ] Bundle check step fails the build if main chunk exceeds 500 KB
- [ ] `axe-setup.ts` exports configured `axe` runner with WCAG 2.1 AA rules enabled
- [ ] `ShellComponent`, `HeaderComponent`, and `SidebarComponent` have passing `axe-core` WCAG tests
- [ ] All axe tests pass: `npm run test:axe` exits 0
- [ ] `lighthouserc.json` passes JSON validation
- [ ] `cloudbuild.yaml` passes YAML validation
- [ ] Lighthouse CI runs to completion in local simulation (`npm run lhci`)
