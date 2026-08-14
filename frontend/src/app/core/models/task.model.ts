/**
 * Agent task response model — matches backend DTO from US-022/US-026.
 * Used by EncounterTasksApiService and SignalRService.
 */
export interface AgentTaskResponse {
  id: string;
  encounter_id: string;
  unit_id: string | null;
  agent_type: string;
  target_role: string | null;
  status: string;
  start_time: string;
  completed_time: string | null;
  started_at: string | null;
  payload: Record<string, any> | null;
  output: Record<string, any> | null;

  // US-021/US-032 SLA and failure context
  sla_breached?: boolean;
  blocked_reason?: string | null;
  error_message?: string | null;
  retry_count?: number;

  // US-026 Documentation completeness
  document_id?: string | null;
  generation_type?: string | null;
  completeness_status?: string | null;
  missing_fields?: string[];
}

/** Maps backend agent_type values to human-readable dashboard labels. */
export const AGENT_TYPE_DISPLAY_NAME: Record<string, string> = {
  coordinator: 'Transition Coordinator',
  documentation: 'Documentation',
  medication_reconciliation: 'Medication Reconciliation',
  bed_management: 'Bed Management',
  follow_up_care: 'Follow-up Care',
  patient_communication: 'Patient Communications',
};

/** Dashboard agent ordering (matches current UI). */
export const DASHBOARD_AGENTS: { name: string; agentType: string }[] = [
  { name: 'Transition Coordinator', agentType: 'coordinator' },
  { name: 'Documentation', agentType: 'documentation' },
  { name: 'Medication Reconciliation', agentType: 'medication_reconciliation' },
  { name: 'Bed Management', agentType: 'bed_management' },
  { name: 'Follow-up Care', agentType: 'follow_up_care' },
  { name: 'Patient Communications', agentType: 'patient_communication' },
];

/**
 * Task status enumeration — matches backend AgentTaskStatus.
 */
export enum TaskStatus {
  PENDING = 'PENDING',
  IN_PROGRESS = 'IN_PROGRESS',
  BLOCKED = 'BLOCKED',
  PENDING_APPROVAL = 'PENDING_APPROVAL',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
  CANCELLED = 'CANCELLED'
}

/**
 * Agent type enumeration — matches backend agent types.
 */
export enum AgentType {
  COORDINATOR = 'COORDINATOR',
  DOCUMENTATION = 'DOCUMENTATION',
  BED_MANAGEMENT = 'BED_MANAGEMENT',
  COMMS = 'COMMS',
  FOLLOWUP_CARE = 'FOLLOWUP_CARE',
  MEDRECON = 'MEDRECON'
}

/**
 * Care team role enumeration — matches backend RBAC roles.
 */
export enum CareTeamRole {
  NURSE = 'nurse',
  PHYSICIAN = 'physician',
  CASE_MANAGER = 'case_manager',
  PHARMACIST = 'pharmacist',
  SOCIAL_WORKER = 'social_worker'
}
