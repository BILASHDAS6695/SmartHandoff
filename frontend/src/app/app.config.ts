import { ApplicationConfig, APP_INITIALIZER, isDevMode, inject } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideServiceWorker } from '@angular/service-worker';
import { routes } from './app.routes';
import { jwtInterceptor } from './core/auth/jwt.interceptor';
import { OfflineCacheService } from './features/patient-portal/discharge-instructions/offline-cache.service';

/**
 * Factory function for APP_INITIALIZER that evicts expired discharge cache entries.
 * Runs once at application startup before any component is instantiated.
 * Handles gracefully if Cache API is unavailable (SSR, tests).
 */
function initOfflineCache(): () => Promise<void> {
  const service = inject(OfflineCacheService);
  return () => service.evictExpiredDischargeCache();
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(withInterceptors([jwtInterceptor])),
    provideServiceWorker('ngsw-worker.js', {
      enabled: !isDevMode(),
      registrationStrategy: 'registerWhenStable:30000',
    }),
    {
      provide: APP_INITIALIZER,
      useFactory: initOfflineCache,
      multi: true,
    },
  ],
};
