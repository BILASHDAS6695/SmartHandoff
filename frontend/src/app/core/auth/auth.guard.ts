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
