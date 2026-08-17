import { Routes } from '@angular/router';
import { RoleGuard } from '../../core/auth/role.guard';

export const PATIENTS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('../dashboard/shell/shell.component').then((m) => m.ShellComponent),
    children: [
      {
        path: '',
        loadComponent: () =>
          import('./components/unique-patients-list/unique-patients-list.component').then((m) => m.UniquePatientsListComponent),
      },
      {
        path: 'register',
        loadComponent: () =>
          import('./components/encounter-register/encounter-register.component').then((m) => m.EncounterRegisterComponent),
      },
      {
        path: ':patientId',
        loadComponent: () =>
          import('./components/patient-detail/patient-detail.component').then((m) => m.PatientDetailComponent),
      },
      {
        path: ':patientId/medications',
        canActivate: [RoleGuard],
        data: { roles: ['pharmacist', 'physician', 'admin'] },
        loadComponent: () =>
          import('../medications/components/medication-review/medication-review.component').then(
            (m) => m.MedicationReviewComponent,
          ),
      },
      {
        path: ':patientId/documents',
        canActivate: [RoleGuard],
        data: { roles: ['physician', 'nurse', 'admin'] },
        loadComponent: () =>
          import('../documents/document-review/document-review.component').then(
            (m) => m.DocumentReviewComponent,
          ),
      },
    ],
  },
];
