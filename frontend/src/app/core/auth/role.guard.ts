import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivate, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { AuthService } from './auth.service';

/**
 * Role Guard — enforces role-based access control on routes.
 *
 * Can be used in two ways:
 * 1. With roles parameter: canActivate: [roleGuard(['manager', 'admin'])]
 * 2. With route data: canActivate: [roleGuard], data: { roles: ['pharmacist'] }
 *
 * Redirects unauthenticated users to /login.
 * Redirects authenticated users without required role to /403 (Forbidden).
 *
 * Usage in route config:
 *   {
 *     path: 'patients/:id/medications',
 *     canActivate: [roleGuard(['pharmacist', 'physician'])],
 *     loadComponent: () => import(...),
 *   }
 */
@Injectable({ providedIn: 'root' })
export class RoleGuard implements CanActivate {
  constructor(
    private readonly auth: AuthService,
    private readonly router: Router,
  ) {}

  canActivate(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): boolean | UrlTree {
    const requiredRoles: string[] = route.data['roles'] ?? [];

    if (!this.auth.isAuthenticated()) {
      return this.router.parseUrl('/login');
    }

    const userRole = this.auth.currentUser()?.role;
    const userRoles: string[] = userRole ? [userRole] : [];
    const hasRole = requiredRoles.length === 0 || requiredRoles.some((r) => userRoles.includes(r));

    if (!hasRole) {
      return this.router.parseUrl('/403');
    }

    return true;
  }
}
