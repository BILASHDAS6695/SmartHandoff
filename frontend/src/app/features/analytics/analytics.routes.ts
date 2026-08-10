import { Routes } from '@angular/router';
import { RoleGuard } from '@core/auth/role.guard';

/**
 * Analytics feature routes.
 * US-061: KPI Analytics Dashboard with Chart.js visualisations
 *
 * Design ref: design.md §3.4, US-047 lazy-loading requirement.
 */
export const ANALYTICS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('../dashboard/shell/shell.component').then((m) => m.ShellComponent),
    canActivate: [RoleGuard],
    data: { roles: ['manager', 'admin'] },
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./analytics.component').then(
            (m) => m.AnalyticsComponent,
          ),
        title: 'Analytics Dashboard — SmartHandoff',
      },
    ],
  },
];
