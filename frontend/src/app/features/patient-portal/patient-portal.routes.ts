import { Routes } from '@angular/router';

export const PATIENT_PORTAL_ROUTES: Routes = [
  {
    path: 'otp',
    loadComponent: () =>
      import('./otp/patient-otp.component').then((m) => m.PatientOtpComponent),
  },
  {
    path: 'instructions/:encounterId',
    loadComponent: () =>
      import('./discharge-instructions/discharge-instructions.component').then(
        (m) => m.DischargeInstructionsComponent,
      ),
  },
];
