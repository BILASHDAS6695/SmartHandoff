import { Routes } from '@angular/router';

export const BEDS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./beds-board/beds-board.component').then((m) => m.BedsBoardComponent),
  },
];
