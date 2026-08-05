import { Routes } from '@angular/router';
import { AuthGuard } from '@core/auth/auth.guard';

export const DASHBOARD_ROUTES: Routes = [
  {
    path: '',
    canActivate: [AuthGuard],
    loadComponent: () =>
      import('./shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./dashboard.component').then((m) => m.DashboardComponent),
      },
    ],
  },
];
