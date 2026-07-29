import { Routes } from '@angular/router';

/**
 * Medications feature routes.
 * Stub module to be populated by US-025 (medications feature stories).
 * Medication review route is now under patients feature at /patients/:patientId/medications.
 *
 * Design ref: design.md §3.4, US-047 lazy-loading requirement.
 */
export const MEDICATIONS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./medications-list/medications-list.component').then(
        (m) => m.MedicationsListComponent,
      ),
  },
];
