import { Routes } from '@angular/router';
import { RoleGuard } from '../../core/auth/role.guard';

export const TASKS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('../dashboard/shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        canActivate: [RoleGuard],
        data: { roles: ['admin'] },
        loadComponent: () =>
          import('./task-monitor/task-monitor.component').then((m) => m.TaskMonitorComponent),
      },
    ],
  },
];
