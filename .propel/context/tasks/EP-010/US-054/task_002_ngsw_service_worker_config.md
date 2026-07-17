---
id: TASK-002
title: "Angular Service Worker Config — ngsw-config.json with 30-Day Discharge Instructions Cache"
user_story: US-054
epic: EP-010
sprint: 2
layer: Frontend / PWA
estimate: 2h
priority: Should Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-053/TASK-001, FR-021, NFR-033]
---

# TASK-002: Angular Service Worker Config — ngsw-config.json with 30-Day Discharge Instructions Cache

> **Story:** US-054 | **Epic:** EP-010 | **Sprint:** 2 | **Layer:** Frontend / PWA | **Est:** 2 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-054 requires that a patient who previously viewed their discharge instructions can re-open the
portal while offline and still see the instructions — loaded from Service Worker cache within 2
seconds. The cache must persist for 30 days post-discharge.

Angular's built-in `@angular/service-worker` manages both static asset precaching and dynamic API
response caching via `ngsw-config.json`. The discharge instructions API response
(`GET /api/v1/encounters/{id}/documents`) must be cached using the `freshness` strategy so that the
SW serves a live response when online and falls back to cache when offline.

Cache TTL is controlled by `maxAge: 30d` in `ngsw-config.json`. Cache expiry based on
`discharge_date + 30 days` is enforced at the application layer in `OfflineCacheService`
(TASK-003), which clears stale entries via SW's `Cache API` during the background sync event.

**Design references:**
- US-054 Scenario 2 — instructions load from cache within 2 s when offline
- US-054 Scenario 3 — cache TTL = 30 days from discharge date
- US-054 DoD — `ngsw-config.json`; `precacheStrategy: 'freshness'` for API responses
- design.md §4.1 — Angular Service Worker (built-in); ADR-005 — Angular 17 PWA
- design.md §3.4 — `features/patient-portal/` module

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|---|---|
| Scenario 2 | Instructions page loads from SW cache within 2 seconds in offline mode |
| Scenario 3 | Discharge instructions JSON response present in cache 15 days post-discharge; cache not expired before 30-day TTL |

---

## Implementation Steps

### 1. Ensure `@angular/service-worker` is installed

```bash
ng add @angular/pwa --project=smarthandoff-angular
# This installs @angular/service-worker, updates angular.json, and creates ngsw-config.json
```

### 2. Implement `ngsw-config.json`

Replace or update `frontend/ngsw-config.json` with the following configuration:

```json
{
  "$schema": "./node_modules/@angular/service-worker/config/schema.json",
  "index": "/index.html",
  "assetGroups": [
    {
      "name": "app-shell",
      "installMode": "prefetch",
      "updateMode": "prefetch",
      "resources": {
        "files": [
          "/favicon.ico",
          "/index.html",
          "/manifest.webmanifest",
          "/*.css",
          "/*.js"
        ]
      }
    },
    {
      "name": "assets",
      "installMode": "lazy",
      "updateMode": "prefetch",
      "resources": {
        "files": [
          "/assets/**"
        ]
      }
    }
  ],
  "dataGroups": [
    {
      "name": "discharge-instructions-api",
      "urls": [
        "/api/v1/encounters/*/documents"
      ],
      "cacheConfig": {
        "strategy": "freshness",
        "maxSize": 50,
        "maxAge": "30d",
        "timeout": "3s"
      }
    },
    {
      "name": "patient-portal-api",
      "urls": [
        "/api/v1/auth/patient/**",
        "/api/v1/encounters/*/summary"
      ],
      "cacheConfig": {
        "strategy": "freshness",
        "maxSize": 20,
        "maxAge": "1d",
        "timeout": "3s"
      }
    }
  ]
}
```

**Key design decisions:**

| Setting | Value | Rationale |
|---|---|---|
| `strategy` | `freshness` | Network-first with cache fallback — always shows latest when online; serves cache offline |
| `maxAge` | `30d` | Matches US-054 Scenario 3 TTL requirement |
| `timeout` | `3s` | Falls back to cache if API does not respond within 3 s (Scenario 2: <2 s render) |
| `maxSize` | `50` | Accommodates up to 50 unique encounter document responses per client |

### 3. Verify `angular.json` service worker registration

Confirm that `angular.json` has `"serviceWorker": true` and `"ngswConfigPath"` set for the
production build configuration:

```json
// In angular.json → projects → smarthandoff-angular → architect → build →
// configurations → production:
{
  "serviceWorker": true,
  "ngswConfigPath": "ngsw-config.json"
}
```

### 4. Register Service Worker in `app.config.ts`

```typescript
// frontend/src/app/app.config.ts
import { provideServiceWorker } from '@angular/service-worker';
import { isDevMode } from '@angular/core';

export const appConfig: ApplicationConfig = {
  providers: [
    // ... existing providers
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
  ],
};
```

### 5. Implement `OfflineCacheService` for discharge-date-based TTL enforcement

```bash
touch frontend/src/app/features/patient-portal/discharge-instructions/offline-cache.service.ts
```

```typescript
/**
 * OfflineCacheService — enforces 30-day discharge-date-based cache TTL (US-054).
 *
 * The Angular SW `ngsw-config.json` sets a 30-day maxAge relative to the time
 * the entry was cached, not the discharge date. This service supplements that
 * by checking the actual discharge date from the cached response and evicting
 * entries whose discharge_date + 30 days has elapsed.
 *
 * Called during app initialisation and on SW background-sync events.
 *
 * Design refs:
 *   US-054 Scenario 3 — cache TTL = 30 days from discharge_date
 *   US-054 DoD        — expired cache cleared by SW background sync
 */
import { Injectable } from '@angular/core';

const CACHE_NAME = 'ngsw:/:data:dynamic:discharge-instructions-api:cache';
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

@Injectable({ providedIn: 'root' })
export class OfflineCacheService {
  /**
   * Evicts cached discharge instruction responses whose discharge_date
   * is more than 30 days in the past.
   *
   * No-op in environments where the Cache API is unavailable (e.g., SSR, tests).
   */
  async evictExpiredDischargeCache(): Promise<void> {
    if (!('caches' in window)) return;

    let cache: Cache;
    try {
      cache = await caches.open(CACHE_NAME);
    } catch {
      // Cache not yet created — nothing to evict.
      return;
    }

    const keys = await cache.keys();

    for (const request of keys) {
      try {
        const response = await cache.match(request);
        if (!response) continue;

        const body = await response.clone().json();
        const dischargeDate: string | undefined = body?.discharge_date;
        if (!dischargeDate) continue;

        const dischargeMs = new Date(dischargeDate).getTime();
        if (Number.isNaN(dischargeMs)) continue;

        if (Date.now() - dischargeMs > THIRTY_DAYS_MS) {
          await cache.delete(request);
        }
      } catch {
        // Malformed entry — leave in place; ngsw maxAge will expire it naturally.
      }
    }
  }
}
```

### 6. Invoke `OfflineCacheService` at app startup

In `app.config.ts`, add an `APP_INITIALIZER` that runs `evictExpiredDischargeCache()`:

```typescript
import { APP_INITIALIZER, inject } from '@angular/core';
import { OfflineCacheService } from './features/patient-portal/discharge-instructions/offline-cache.service';

function initOfflineCache(): () => Promise<void> {
  const service = inject(OfflineCacheService);
  return () => service.evictExpiredDischargeCache();
}

// Add to providers array in appConfig:
{
  provide: APP_INITIALIZER,
  useFactory: initOfflineCache,
  multi: true,
}
```

---

## Files Affected

| File | Action |
|---|---|
| `frontend/ngsw-config.json` | **Create / Replace** — full SW cache configuration |
| `frontend/src/app/app.config.ts` | **Modify** — `provideServiceWorker` + `APP_INITIALIZER` |
| `frontend/angular.json` | **Modify** — confirm `serviceWorker: true` in production config |
| `frontend/src/app/features/patient-portal/discharge-instructions/offline-cache.service.ts` | **Create** — discharge-date-based cache eviction |

---

## Validation

- [ ] `ng build --configuration=production` generates `ngsw-worker.js` and `ngsw.json` in `dist/`
- [ ] Chrome DevTools → Application → Service Workers: SW registered and status "activated and is running"
- [ ] Load instructions page online → Chrome DevTools → Application → Cache Storage → `discharge-instructions-api` cache entry present
- [ ] Enable Chrome DevTools offline mode → reload → instructions page renders within 2 seconds from cache
- [ ] Chrome DevTools → Network tab: all requests blocked (offline); page still loads
- [ ] `OfflineCacheService.evictExpiredDischargeCache()` called on app init without throwing errors
