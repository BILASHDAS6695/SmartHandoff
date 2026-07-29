/**
 * Agent task domain model.
 * Represents a single AI agent task on an encounter.
 */

/**
 * Represents a single AI agent task on an encounter.
 * Received from GET /api/v1/encounters/{id}/agent-tasks or via SignalR push.
 */
export interface AgentTask {
  agentType: AgentType;
  status: AgentStatus;
  /** ISO 8601 — when the task was last updated */
  updatedAt: string;
  /** True when current timestamp exceeds SLA deadline for this agent */
  slaBreach: boolean;
  /** SLA deadline ISO 8601 */
  slaDeadline: string;
}

export type AgentStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';

export type AgentType =
  | 'TRANSITION_COORDINATOR'
  | 'DOCUMENTATION'
  | 'MEDICATION_RECONCILIATION'
  | 'BED_MANAGEMENT'
  | 'FOLLOW_UP_CARE';

/** Human-readable display name per agent type */
export const AGENT_DISPLAY_NAMES: Record<AgentType, string> = {
  TRANSITION_COORDINATOR: 'Transition Coordinator',
  DOCUMENTATION: 'Documentation',
  MEDICATION_RECONCILIATION: 'Medication Reconciliation',
  BED_MANAGEMENT: 'Bed Management',
  FOLLOW_UP_CARE: 'Follow-up Care',
};
