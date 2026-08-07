import { Routes } from '@angular/router';
import { AuthGuard } from '@core/auth/auth.guard';
import { ShellComponent } from '@features/dashboard/shell/shell.component';

export const AUDIT_LOG_ROUTES: Routes = [
  {
    path: '',
    canActivate: [AuthGuard],
    component: ShellComponent,
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./audit-log.component').then((m) => m.AuditLogComponent),
      },
    ],
  },
];
