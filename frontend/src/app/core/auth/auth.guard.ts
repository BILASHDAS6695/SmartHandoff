import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivate, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { AuthService } from './auth.service';
import { environment } from '../../../environments/environment';

/**
 * AuthGuard — protects routes that require an authenticated session.
 *
 * Checks AuthService.isAuthenticated() (computed signal that validates
 * JWT expiry). Redirects to /login if no valid token is present.
 *
 * DEV MODE: Set SKIP_AUTH=true in environment to bypass authentication for testing.
 *
 * Usage in route config:
 *   {
 *     path: 'dashboard',
 *     canActivate: [authGuard],
 *     loadComponent: () => import('../features/dashboard/dashboard.component')
 *       .then(m => m.DashboardComponent),
 *   }
 */
@Injectable({ providedIn: 'root' })
export class AuthGuard implements CanActivate {
  constructor(
    private readonly authService: AuthService,
    private readonly router: Router,
  ) {}

  canActivate(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): boolean | UrlTree {
    // DEV MODE: Skip authentication if SKIP_AUTH is enabled
    if ((environment as any).SKIP_AUTH === true) {
      console.warn('⚠️  AUTH GUARD BYPASSED - Development mode only!');
      return true;
    }

    if (this.authService.isAuthenticated()) {
      return true;
    }

    // Redirect to login; preserve attempted URL for post-login redirect
    const returnUrl = state.url || '/';
    return this.router.createUrlTree(['/login'], {
      queryParams: { returnUrl },
    });
  }
}
