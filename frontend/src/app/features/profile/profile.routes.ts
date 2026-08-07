import { Routes } from '@angular/router';
import { AuthGuard } from '@core/auth/auth.guard';
import { ShellComponent } from '@features/dashboard/shell/shell.component';

export const PROFILE_ROUTES: Routes = [
  {
    path: '',
    canActivate: [AuthGuard],
    component: ShellComponent,
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./profile.component').then((m) => m.ProfileComponent),
      },
    ],
  },
];
