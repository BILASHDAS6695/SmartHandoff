import { Routes } from '@angular/router';

export const TASKS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('../dashboard/shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./task-monitor/task-monitor.component').then((m) => m.TaskMonitorComponent),
      },
    ],
  },
];
