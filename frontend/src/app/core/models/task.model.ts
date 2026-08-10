/**
 * Agent task response model — matches backend DTO from US-022.
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
}

/**
 * Task status enumeration — matches backend AgentTaskStatus.
 */
export enum TaskStatus {
  PENDING = 'PENDING',
  IN_PROGRESS = 'IN_PROGRESS',
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
