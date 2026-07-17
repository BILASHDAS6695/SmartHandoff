---
id: TASK-001
title: "Angular 17 Workspace Scaffold — angular.json, tsconfig, ESLint, PWA manifest"
user_story: US-047
epic: EP-009
sprint: 2
layer: Frontend / Configuration
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-047, TR-002, NFR-001]
---

# TASK-001: Angular 17 Workspace Scaffold — angular.json, tsconfig, ESLint, PWA manifest

> **Story:** US-047 | **Epic:** EP-009 | **Sprint:** 2 | **Layer:** Frontend / Configuration | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

This task creates the Angular 17 application skeleton that all subsequent feature tasks build on. It establishes the workspace configuration files, TypeScript strict-mode settings, ESLint rules, Angular PWA service-worker manifest, and build budgets that enforce the <500 KB main chunk constraint from TR-002.

All new components must use `standalone: true` per the US-047 Technical Notes. The `provideHttpClient` approach (not `HttpClientModule`) is required for interceptor registration.

### Artefacts required

| Artefact | Type | Description |
|----------|------|-------------|
| `angular.json` | Config | Workspace config with build budgets (warn 400 KB, error 500 KB) |
| `tsconfig.json` | Config | Base TypeScript config — strict mode, ES2022, path aliases |
| `tsconfig.app.json` | Config | App-specific TS config extending base |
| `tsconfig.spec.json` | Config | Test-specific TS config |
| `.eslintrc.json` | Config | ESLint with `@angular-eslint` and `@typescript-eslint` rule sets |
| `ngsw-config.json` | Config | Angular service worker PWA caching strategy |
| `src/manifest.webmanifest` | PWA | PWA manifest (name, icons, theme colour, display: standalone) |
| `src/main.ts` | Bootstrap | `bootstrapApplication` with `provideHttpClient`, `provideRouter` |
| `src/app/app.config.ts` | Config | `ApplicationConfig` with providers array |
| `src/app/app.routes.ts` | Routing | Root routes — all feature routes lazy-loaded via `loadChildren` |
| `src/environments/environment.ts` | Config | Dev environment variables (apiUrl, signalrUrl, production: false) |
| `src/environments/environment.prod.ts` | Config | Prod environment variables (production: true) |
| `package.json` | Dependencies | Angular 17, Angular Material 17, @angular/pwa, jest, @types/jest |

**Design references:**
- design.md §3.4 — Frontend Module Architecture
- design.md §4.1 — Angular 17, Angular Material 17 technology selection
- design.md §5.1 TR-002 — Angular initial page load <2 s, main chunk <500 KB
- US-047 Technical Notes — standalone components, `withInterceptors`, bundle budgets

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 1 | Bundle budget `maximumError: "500kb"` enforced in `angular.json`; breaks build if exceeded |
| Scenario 2 | All feature routes use `loadChildren` — no eager imports |

---

## Implementation Steps

### 1. Initialise Angular 17 workspace

```bash
# Run from repository root
npx @angular/cli@17 new smarthandoff-angular \
  --routing=false \
  --style=scss \
  --strict \
  --standalone \
  --ssr=false \
  --skip-git

cd smarthandoff-angular

# Add Angular Material 17
ng add @angular/material@17 --theme=custom --typography=true --animations=enabled

# Add PWA support
ng add @angular/pwa@17

# Add ESLint
ng add @angular-eslint/schematics@17

# Jest (replaces Karma)
npm install --save-dev jest jest-preset-angular @types/jest ts-jest
npm uninstall karma karma-chrome-launcher karma-coverage karma-jasmine jasmine-core
```

### 2. Create `tsconfig.json`

```json
{
  "compileOnSave": false,
  "compilerOptions": {
    "baseUrl": "./",
    "outDir": "./dist/out-tsc",
    "forceConsistentCasingInFileNames": true,
    "strict": true,
    "noImplicitOverride": true,
    "noPropertyAccessFromIndexSignature": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "esModuleInterop": true,
    "sourceMap": true,
    "declaration": false,
    "downlevelIteration": true,
    "experimentalDecorators": true,
    "moduleResolution": "bundler",
    "importHelpers": true,
    "target": "ES2022",
    "module": "ES2022",
    "useDefineForClassFields": false,
    "lib": ["ES2022", "dom"],
    "paths": {
      "@core/*": ["src/app/core/*"],
      "@shared/*": ["src/app/shared/*"],
      "@features/*": ["src/app/features/*"],
      "@env/*": ["src/environments/*"]
    }
  },
  "angularCompilerOptions": {
    "enableI18nLegacyMessageIdFormat": false,
    "strictInjectionParameters": true,
    "strictInputAccessModifiers": true,
    "strictTemplates": true
  }
}
```

### 3. Configure build budgets in `angular.json`

Locate the `configurations.production.budgets` array and set:

```json
"budgets": [
  {
    "type": "initial",
    "maximumWarning": "400kb",
    "maximumError": "500kb"
  },
  {
    "type": "anyComponentStyle",
    "maximumWarning": "4kb",
    "maximumError": "8kb"
  }
]
```

Also add `"sourceMap": false` under `configurations.production` and enable `"namedChunks": false`.

### 4. Create `src/app/app.routes.ts`

```typescript
// Root application routes for SmartHandoff Angular 17 PWA.
// All feature modules are lazy-loaded — no feature code in the initial bundle.
// Design ref: design.md §3.4, US-047 Scenario 2 (lazy loading only on navigation)

import { Routes } from '@angular/router';

export const APP_ROUTES: Routes = [
  {
    path: '',
    redirectTo: 'dashboard',
    pathMatch: 'full',
  },
  {
    path: 'dashboard',
    loadChildren: () =>
      import('./features/dashboard/dashboard.routes').then((m) => m.DASHBOARD_ROUTES),
  },
  {
    path: 'patients',
    loadChildren: () =>
      import('./features/patients/patients.routes').then((m) => m.PATIENTS_ROUTES),
  },
  {
    path: 'beds',
    loadChildren: () =>
      import('./features/beds/beds.routes').then((m) => m.BEDS_ROUTES),
  },
  {
    path: 'medications',
    loadChildren: () =>
      import('./features/medications/medications.routes').then((m) => m.MEDICATIONS_ROUTES),
  },
  {
    path: 'documents',
    loadChildren: () =>
      import('./features/documents/documents.routes').then((m) => m.DOCUMENTS_ROUTES),
  },
  {
    path: 'analytics',
    loadChildren: () =>
      import('./features/analytics/analytics.routes').then((m) => m.ANALYTICS_ROUTES),
  },
  {
    path: 'admin',
    loadChildren: () =>
      import('./features/admin/admin.routes').then((m) => m.ADMIN_ROUTES),
  },
  {
    path: 'portal',
    loadChildren: () =>
      import('./features/patient-portal/patient-portal.routes').then(
        (m) => m.PATIENT_PORTAL_ROUTES,
      ),
  },
  {
    path: '**',
    redirectTo: 'dashboard',
  },
];
```

### 5. Create `src/app/app.config.ts`

```typescript
// Root ApplicationConfig — registers global providers without NgModules.
// Uses standalone API per US-047 Technical Notes.

import { ApplicationConfig, isDevMode } from '@angular/core';
import { provideRouter, withPreloading, PreloadAllModules } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';
import { provideServiceWorker } from '@angular/service-worker';

import { APP_ROUTES } from './app.routes';
import { jwtInterceptor } from './core/auth/jwt.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(APP_ROUTES, withPreloading(PreloadAllModules)),
    provideHttpClient(withInterceptors([jwtInterceptor])),
    provideAnimations(),
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
```

### 6. Create `src/main.ts`

```typescript
import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

bootstrapApplication(AppComponent, appConfig).catch((err) => console.error(err));
```

### 7. Create `src/app/app.component.ts` (shell)

```typescript
import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  template: `<router-outlet />`,
})
export class AppComponent {}
```

### 8. Create `src/environments/environment.ts`

```typescript
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api/v1',
  signalrUrl: 'http://localhost:8000/hubs/dashboard',
  apiOrigin: 'http://localhost:8000',
};
```

### 9. Create `src/environments/environment.prod.ts`

```typescript
export const environment = {
  production: true,
  apiUrl: '/api/v1',
  signalrUrl: '/hubs/dashboard',
  apiOrigin: '',   // same-origin in prod — JWT interceptor uses this to scope token attachment
};
```

### 10. Configure Jest (`jest.config.ts`)

```typescript
import type { Config } from 'jest';

const config: Config = {
  preset: 'jest-preset-angular',
  setupFilesAfterFramework: ['<rootDir>/setup-jest.ts'],
  testPathPattern: ['src/**/*.spec.ts'],
  collectCoverageFrom: ['src/**/*.ts', '!src/**/*.spec.ts', '!src/main.ts'],
  coverageThresholds: {
    global: { branches: 80, functions: 80, lines: 80, statements: 80 },
  },
};

export default config;
```

### 11. Create `setup-jest.ts`

```typescript
import 'jest-preset-angular/setup-jest';
```

### 12. Create feature module stub route files

Create empty stub route files for each feature so the lazy imports in `app.routes.ts` resolve:

```bash
for feature in dashboard patients beds medications documents analytics admin patient-portal; do
  mkdir -p src/app/features/$feature
  # Route stub — replaced by feature task implementations
done
```

Each stub (e.g., `dashboard.routes.ts`):

```typescript
import { Routes } from '@angular/router';

export const DASHBOARD_ROUTES: Routes = [
  // Populated by TASK-005 (dashboard shell) and feature tasks
];
```

---

## Validation Script

```bash
# Verify TypeScript strict compilation
npx tsc --noEmit

# Verify ESLint passes
npx eslint "src/**/*.ts" --max-warnings=0

# Verify dev build succeeds under budget
npx ng build --configuration=development

# Verify production build does NOT exceed 500 KB main chunk
npx ng build --configuration=production 2>&1 | grep -E "main\.|budget"

# Verify lazy route chunks are separate files (not in main bundle)
npx ng build --configuration=production --stats-json
node -e "
const stats = require('./dist/smarthandoff-angular/browser/stats.json');
const main = stats.assets.find(a => a.name.startsWith('main'));
const patients = stats.assets.find(a => a.name.includes('patients'));
console.assert(main, 'main chunk must exist');
console.assert(patients, 'patients chunk must be a separate file (lazy)');
console.log('main chunk size:', main.size, 'bytes');
console.log('Lazy patients chunk:', patients.name, '✓');
"
```

---

## Definition of Done

- [ ] `angular.json` created with `maximumWarning: "400kb"` and `maximumError: "500kb"` build budgets
- [ ] `tsconfig.json` has `strict: true`, `target: "ES2022"`, and path aliases (`@core/*`, `@shared/*`, `@features/*`)
- [ ] `.eslintrc.json` configured with `@angular-eslint` and `@typescript-eslint` rule sets; no lint errors
- [ ] `app.routes.ts` uses `loadChildren` for all 8 feature paths — no eager imports
- [ ] `app.config.ts` uses `provideHttpClient(withInterceptors([jwtInterceptor]))` — no `HttpClientModule`
- [ ] All feature stub route files created and importable
- [ ] `ngsw-config.json` and `src/manifest.webmanifest` present and valid
- [ ] Jest configured; `npm test` runs without errors
- [ ] `npm run build -- --configuration=production` succeeds and main chunk is under 500 KB
- [ ] `npx tsc --noEmit` passes with zero errors
