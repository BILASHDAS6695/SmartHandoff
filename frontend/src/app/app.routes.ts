import { Routes } from '@angular/router';
import { authGuard } from './core/auth/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    loadComponent: () =>
      import('./features/auth/login/login.component').then(m => m.LoginComponent),
  },
  {
    path: 'auth/callback',
    loadComponent: () =>
      import('./features/auth/callback/login-callback.component')
        .then(m => m.LoginCallbackComponent),
  },
  {
    path: 'dashboard',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/dashboard/dashboard.routes').then((m) => m.DASHBOARD_ROUTES),
  },
  {
    path: 'patients',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/patients/patients.routes').then((m) => m.PATIENTS_ROUTES),
  },
  {
    path: 'beds',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/beds/beds.routes').then((m) => m.BEDS_ROUTES),
  },
  {
    path: 'documents',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/documents/documents.routes').then((m) => m.DOCUMENTS_ROUTES),
  },
  {
    path: 'medications',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/medications/medications.routes').then((m) => m.MEDICATIONS_ROUTES),
  },
  {
    path: 'analytics',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/analytics/analytics.routes').then((m) => m.ANALYTICS_ROUTES),
  },
  {
    path: 'admin',
    canActivate: [authGuard],
    loadChildren: () =>
      import('./features/admin/admin.routes').then((m) => m.ADMIN_ROUTES),
  },
  {
    path: 'portal',
    loadChildren: () =>
      import('./features/patient-portal/patient-portal.routes').then(
        (m) => m.PATIENT_PORTAL_ROUTES,
      ),
  },
  // Default redirect
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: '**', redirectTo: 'dashboard' },
];

