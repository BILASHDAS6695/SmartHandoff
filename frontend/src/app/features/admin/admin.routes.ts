import { Routes } from '@angular/router';

/**
 * Admin feature routes.
 * Stub module to be populated by future admin feature stories.
 *
 * Design ref: design.md §3.4, US-047 lazy-loading requirement.
 */
export const ADMIN_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./admin-panel/admin-panel.component').then(
        (m) => m.AdminPanelComponent,
      ),
  },
];
