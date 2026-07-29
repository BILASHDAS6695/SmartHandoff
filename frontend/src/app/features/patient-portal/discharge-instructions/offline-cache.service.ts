/**
 * OfflineCacheService — enforces 30-day discharge-date-based cache TTL (US-054).
 *
 * The Angular SW `ngsw-config.json` sets a 30-day maxAge relative to the time
 * the entry was cached, not the discharge date. This service supplements that
 * by checking the actual discharge date from the cached response and evicting
 * entries whose discharge_date + 30 days has elapsed.
 *
 * Called during app initialisation via APP_INITIALIZER and on SW background-sync events.
 *
 * Design refs:
 *   US-054 Scenario 3 — cache TTL = 30 days from discharge_date
 *   US-054 DoD        — expired cache cleared by SW background sync
 *   US-054 TASK-002   — OfflineCacheService implementation
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
   * Safe to call at any time:
   * - No-op in environments where the Cache API is unavailable (e.g., SSR, tests)
   * - Silent failure if cache does not yet exist
   * - Gracefully handles malformed entries (skipped, left for natural maxAge expiration)
   */
  async evictExpiredDischargeCache(): Promise<void> {
    if (!('caches' in window)) {
      return;
    }

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
        if (!response) {
          continue;
        }

        const body = await response.clone().json();
        const dischargeDate: string | undefined = body?.discharge_date;
        if (!dischargeDate) {
          continue;
        }

        const dischargeMs = new Date(dischargeDate).getTime();
        if (Number.isNaN(dischargeMs)) {
          continue;
        }

        // Check if discharge_date + 30 days has elapsed
        if (Date.now() - dischargeMs > THIRTY_DAYS_MS) {
          await cache.delete(request);
        }
      } catch {
        // Malformed entry — leave in place; ngsw maxAge will expire it naturally.
      }
    }
  }
}
