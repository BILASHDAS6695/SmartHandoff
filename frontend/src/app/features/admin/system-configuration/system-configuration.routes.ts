import { Routes } from '@angular/router';
import { AuthGuard } from '@core/auth/auth.guard';
import { ShellComponent } from '@features/dashboard/shell/shell.component';

export const SYSTEM_CONFIGURATION_ROUTES: Routes = [
  {
    path: '',
    canActivate: [AuthGuard],
    component: ShellComponent,
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./system-configuration.component').then((m) => m.SystemConfigurationComponent),
      },
    ],
  },
];
