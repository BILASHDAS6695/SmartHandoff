import { Routes } from '@angular/router';
import { AuthGuard } from '@core/auth/auth.guard';
import { ShellComponent } from '@features/dashboard/shell/shell.component';

export const SWITCH_ROLE_ROUTES: Routes = [
  {
    path: '',
    canActivate: [AuthGuard],
    component: ShellComponent,
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./switch-role.component').then((m) => m.SwitchRoleComponent),
      },
    ],
  },
];
