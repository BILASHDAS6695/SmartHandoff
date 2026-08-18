/**
 * Role model — canonical RBAC roles used across the SmartHandoff frontend.
 *
 * Mirrors the backend AppUser.role column values. Use these constants instead
 * of string literals so role checks stay consistent as the matrix evolves.
 */
export const Role = {
  Admin: 'admin',
  Physician: 'physician',
  Nurse: 'nurse',
  Pharmacist: 'pharmacist',
  BedManager: 'bed_manager',
} as const;

export type Role = (typeof Role)[keyof typeof Role];

/** Roles that may appear in the UI but are not formal staff roles (e.g. agents). */
export const UI_ROLE_LABELS: Record<string, string> = {
  [Role.Admin]: 'Administrator',
  [Role.Physician]: 'Physician',
  [Role.Nurse]: 'Nurse',
  [Role.Pharmacist]: 'Pharmacist',
  [Role.BedManager]: 'Bed Manager',
  coordinator: 'Transition Coordinator',
  documentation: 'Documentation Agent',
  medication_reconciliation: 'Medication Reconciliation Agent',
  bed_management: 'Bed Management Agent',
  follow_up_care: 'Follow-up Care Agent',
  patient_communication: 'Patient Communication Agent',
};

/** Roles that are allowed to use the in-app Switch Role feature. */
export const SWITCH_ROLE_ALLOWED_ROLES: readonly string[] = [Role.Admin];

/** All clinical roles an admin may assume via Switch Role. */
export const SWITCH_ROLE_OPTIONS: readonly string[] = [
  Role.Nurse,
  Role.Physician,
  Role.Pharmacist,
  Role.BedManager,
  Role.Admin,
];

/** Dashboard section visibility by role. */
export const DASHBOARD_SECTION_ROLES: {
  pendingTasks: readonly string[];
  adtFeed: readonly string[];
  riskOverview: readonly string[];
  agentStatus: readonly string[];
} = {
  pendingTasks: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.Admin],
  adtFeed: [Role.BedManager, Role.Admin],
  riskOverview: [Role.Nurse, Role.Physician, Role.Admin],
  agentStatus: [Role.Admin],
};

/** Patient detail tab visibility by role. */
export const PATIENT_DETAIL_TAB_ROLES: {
  Overview: readonly string[];
  Medications: readonly string[];
  Documents: readonly string[];
  Tasks: readonly string[];
  Timeline: readonly string[];
} = {
  Overview: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager, Role.Admin],
  Medications: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.Admin],
  Documents: [Role.Nurse, Role.Physician, Role.Admin],
  Tasks: [Role.Nurse, Role.Physician, Role.Admin],
  Timeline: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager, Role.Admin],
};

/**
 * Dashboard data source visibility by role. Prevents unauthorized API calls.
 * Must stay in sync with backend/config/rbac_permissions.yaml.
 */
export function roleCanFetchDashboard(role: string, source: 'tasks' | 'patients' | 'beds' | 'documents' | 'alerts' | 'medications' | 'physicianAlerts' | 'analytics'): boolean {
  const matrix: Record<string, string[]> = {
    tasks: [Role.Nurse, Role.Physician, Role.Admin],
    patients: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.Admin],
    beds: [Role.BedManager, Role.Admin],
    documents: [Role.Physician, Role.Admin],
    alerts: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager, Role.Admin],
    medications: [Role.Physician, Role.Pharmacist, Role.Admin],
    physicianAlerts: [Role.Physician, Role.Admin],
    analytics: [Role.Admin],
  };
  return matrix[source]?.includes(role.toLowerCase()) ?? false;
}

/** Configuration for each actionable dashboard card. */
export interface DashboardCardConfig {
  id: string;
  title: string;
  icon: string;
  roles: readonly string[];
  emptyText: string;
  viewAllRoute?: string;
  actionLabel?: string;
}

export const DASHBOARD_CARDS: DashboardCardConfig[] = [
  {
    id: 'pendingTasks',
    title: 'My Pending Tasks',
    icon: 'assignment',
    roles: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.Admin],
    emptyText: 'No pending tasks',
    viewAllRoute: '/tasks',
    actionLabel: 'View all',
  },
  {
    id: 'pendingApprovals',
    title: 'Pending Approvals',
    icon: 'approval',
    roles: [Role.Physician, Role.Admin],
    emptyText: 'No documents pending review',
    viewAllRoute: '/documents',
    actionLabel: 'Review queue',
  },
  {
    id: 'pharmacistAlerts',
    title: 'Medication Alerts',
    icon: 'medication',
    roles: [Role.Pharmacist, Role.Admin],
    emptyText: 'No active medication alerts',
  },
  {
    id: 'physicianAlerts',
    title: 'Physician Reviews',
    icon: 'assignment_late',
    roles: [Role.Physician, Role.Admin],
    emptyText: 'No pending physician reviews',
    viewAllRoute: '/tasks',
    actionLabel: 'View reviews',
  },
  {
    id: 'riskOverview',
    title: 'Active Patients — Risk Overview',
    icon: 'monitor_heart',
    roles: [Role.Nurse, Role.Physician, Role.Admin],
    emptyText: 'No active patients',
    viewAllRoute: '/patients',
    actionLabel: 'View all patients',
  },
  {
    id: 'bedCensus',
    title: 'Bed Census',
    icon: 'hotel',
    roles: [Role.BedManager, Role.Admin],
    emptyText: 'No bed census data',
    viewAllRoute: '/beds',
    actionLabel: 'Open bed board',
  },
  {
    id: 'adtFeed',
    title: 'Live ADT Events',
    icon: 'swap_horiz',
    roles: [Role.BedManager, Role.Admin],
    emptyText: 'Waiting for ADT events...',
    viewAllRoute: '/beds',
    actionLabel: 'Bed board',
  },
  {
    id: 'edBoarding',
    title: 'ED Boarding',
    icon: 'emergency',
    roles: [Role.BedManager, Role.Admin],
    emptyText: 'No ED boarding alerts',
    viewAllRoute: '/beds',
    actionLabel: 'Resolve boarding',
  },
  {
    id: 'agentStatus',
    title: 'Agent Status',
    icon: 'smart_toy',
    roles: [Role.Admin],
    emptyText: 'No agent status data',
    viewAllRoute: '/analytics',
    actionLabel: 'Analytics',
  },
  {
    id: 'quickLinks',
    title: 'Quick Links',
    icon: 'apps',
    roles: [Role.Admin, Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager],
    emptyText: 'No quick links',
  },
];

/** Ordered list of card IDs to render for a given role. */
export function dashboardCardOrderForRole(role: string): string[] {
  const order: Record<string, string[]> = {
    [Role.Admin]: ['agentStatus', 'pendingTasks', 'pendingApprovals', 'physicianAlerts', 'pharmacistAlerts', 'riskOverview', 'bedCensus', 'adtFeed', 'quickLinks'],
    [Role.Physician]: ['pendingApprovals', 'physicianAlerts', 'pendingTasks', 'riskOverview', 'quickLinks'],
    [Role.Nurse]: ['pendingTasks', 'riskOverview', 'quickLinks'],
    [Role.Pharmacist]: ['pharmacistAlerts', 'pendingTasks', 'quickLinks'],
    [Role.BedManager]: ['bedCensus', 'adtFeed', 'edBoarding', 'quickLinks'],
  };
  return order[role.toLowerCase()] ?? ['quickLinks'];
}

/** Quick-link destinations by role. */
export function quickLinksForRole(role: string): { label: string; route: string; icon: string }[] {
  const common = [
    { label: 'Patients', route: '/patients', icon: 'people' },
    { label: 'Tasks', route: '/tasks', icon: 'assignment' },
  ];
  const roleLinks: Record<string, { label: string; route: string; icon: string }[]> = {
    [Role.Admin]: [
      { label: 'Admin Panel', route: '/admin', icon: 'admin_panel_settings' },
      { label: 'Analytics', route: '/analytics', icon: 'analytics' },
      { label: 'Bed Board', route: '/beds', icon: 'hotel' },
      { label: 'Documents', route: '/documents', icon: 'description' },
      { label: 'Medications', route: '/medications', icon: 'medication' },
    ],
    [Role.Physician]: [
      { label: 'Documents', route: '/documents', icon: 'description' },
      { label: 'Medications', route: '/medications', icon: 'medication' },
    ],
    [Role.Nurse]: [
      { label: 'Medications', route: '/medications', icon: 'medication' },
    ],
    [Role.Pharmacist]: [
      { label: 'Medications', route: '/medications', icon: 'medication' },
    ],
    [Role.BedManager]: [
      { label: 'Bed Board', route: '/beds', icon: 'hotel' },
    ],
  };
  return [...(roleLinks[role.toLowerCase()] ?? []), ...common];
}

/** Default patient-detail tab to open when a dashboard item is clicked for a given role. */
export function patientDetailTabForRole(role: string): string {
  const map: Record<string, string> = {
    [Role.Physician]: 'Documents',
    [Role.Nurse]: 'Tasks',
    [Role.Pharmacist]: 'Medications',
    [Role.BedManager]: 'Timeline',
    [Role.Admin]: 'Overview',
  };
  return map[role.toLowerCase()] ?? 'Overview';
}

/**
 * Patient-detail data-source visibility by role. Prevents unauthorized API calls
 * for tabs/sections a role cannot access. Must stay in sync with
 * backend/config/rbac_permissions.yaml.
 */
export function roleCanFetchPatientDetail(
  role: string,
  source: 'patient' | 'tasks' | 'documents' | 'medications' | 'alerts' | 'timeline'
): boolean {
  const matrix: Record<string, string[]> = {
    patient: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager, Role.Admin],
    tasks: [Role.Nurse, Role.Physician, Role.Admin],
    documents: [Role.Nurse, Role.Physician, Role.Admin],
    medications: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.Admin],
    alerts: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager, Role.Admin],
    timeline: [Role.Nurse, Role.Physician, Role.Pharmacist, Role.BedManager, Role.Admin],
  };
  return matrix[source]?.includes(role.toLowerCase()) ?? false;
}
