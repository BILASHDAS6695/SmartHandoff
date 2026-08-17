import { Routes } from '@angular/router';

export const ENCOUNTERS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('../dashboard/shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./components/patient-list/patient-list.component').then((m) => m.PatientListComponent),
      },
    ],
  },
];
