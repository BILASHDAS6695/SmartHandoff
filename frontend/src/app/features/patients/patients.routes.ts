import { Routes } from '@angular/router';
import { RoleGuard } from '../../core/auth/role.guard';

export const PATIENTS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./components/patient-list/patient-list.component').then((m) => m.PatientListComponent),
  },
  {
    path: ':patientId/medications',
    canActivate: [RoleGuard],
    data: { roles: ['pharmacist', 'physician'] },
    loadComponent: () =>
      import('../medications/components/medication-review/medication-review.component').then(
        (m) => m.MedicationReviewComponent,
      ),
  },
];
