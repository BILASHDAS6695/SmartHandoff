import { inject } from '@angular/core';
import { CanActivateFn, ActivatedRouteSnapshot, RouterStateSnapshot, Router } from '@angular/router';
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
export function roleGuard(roles?: string[]): CanActivateFn {
  return (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
    const auth = inject(AuthService);
    const router = inject(Router);
    const requiredRoles: string[] = roles ?? route.data['roles'] ?? [];

    if (!auth.isAuthenticated()) {
      return router.parseUrl('/login');
    }

    const userRoles: string[] = auth.currentUser()?.role ? [auth.currentUser()!.role] : [];
    const hasRole = requiredRoles.length === 0 || requiredRoles.some((r) => userRoles.includes(r));

    if (!hasRole) {
      return router.parseUrl('/403');
    }

    return true;
  };
}
