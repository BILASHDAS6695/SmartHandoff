import { Routes } from '@angular/router';
import { AuthGuard } from './core/auth/auth.guard';

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
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/dashboard/dashboard.routes').then((m) => m.DASHBOARD_ROUTES),
  },
  {
    path: 'patients',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/patients/patients.routes').then((m) => m.PATIENTS_ROUTES),
  },
  {
    path: 'beds',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/beds/beds.routes').then((m) => m.BEDS_ROUTES),
  },
  {
    path: 'documents',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/documents/documents.routes').then((m) => m.DOCUMENTS_ROUTES),
  },
  {
    path: 'medications',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/medications/medications.routes').then((m) => m.MEDICATIONS_ROUTES),
  },
  {
    path: 'analytics',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/analytics/analytics.routes').then((m) => m.ANALYTICS_ROUTES),
  },
  {
    path: 'admin',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/admin/admin.routes').then((m) => m.ADMIN_ROUTES),
  },
  {    path: 'admin/audit-log',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/admin/audit-log/audit-log.routes').then((m) => m.AUDIT_LOG_ROUTES),
  },
  {    path: 'admin/system-configuration',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/admin/system-configuration/system-configuration.routes').then(
        (m) => m.SYSTEM_CONFIGURATION_ROUTES,
      ),
  },
  {    path: 'profile',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/profile/profile.routes').then((m) => m.PROFILE_ROUTES),
  },
  {
    path: 'switch-role',
    canActivate: [AuthGuard],
    loadChildren: () =>
      import('./features/switch-role/switch-role.routes').then((m) => m.SWITCH_ROLE_ROUTES),
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

