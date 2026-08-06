import { Routes } from '@angular/router';

export const BEDS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('../dashboard/shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./components/bed-board/bed-board.component').then((m) => m.BedBoardComponent),
      },
    ],
  },
];
