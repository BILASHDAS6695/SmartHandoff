/**
 * TypeScript interfaces for all SignalR event payloads from the FastAPI backend.
 * Each interface maps 1:1 to a server-sent event type.
 *
 * US-048: Integrate SignalR for Real-Time Dashboard Updates
 */

import { TaskStatus } from '../models/task.model';

export interface AdtEventPayload {
  /** HL7 event type code: A01, A02, A03, A08, etc. */
  eventType: string;
  /** Patient unit identifier, e.g. "3A" */
  patientUnit: string;
  /** ISO-8601 timestamp of the event */
  timestamp: string;
  /** EHR encounter identifier */
  encounterId: string;
  /** Human-readable patient name (masked per HIPAA display rules) */
  patientDisplayName: string;
}

export interface TaskUpdatedPayload {
  /** Agent task unique identifier */
  taskId?: string;
  /** Backend snake_case alias for taskId. */
  task_id?: string;
  encounterId?: string;
  encounter_id?: string;
  /** Task type label, e.g. "Documentation Agent" */
  taskName?: string;
  /** Previous task status */
  previousStatus?: TaskStatus;
  /** Backend snake_case alias for previousStatus. */
  previous_status?: TaskStatus;
  /** New task status */
  newStatus?: TaskStatus;
  /** Backend snake_case alias for newStatus. */
  new_status?: TaskStatus;
  /** ISO-8601 completion timestamp (present when newStatus === 'COMPLETED') */
  completedAt?: string;
  /** Backend snake_case alias for completedAt. */
  completed_at?: string;
  /** ISO-8601 timestamp of the DB write / event broadcast. */
  updatedAt?: string;
  /** Backend snake_case alias for updatedAt. */
  updated_at?: string;
  /** Agent type that changed state (e.g. "DOCUMENTATION" or "medication_reconciliation"). */
  agentType?: string;
  /** Backend snake_case alias for agentType. */
  agent_type?: string;
}

export interface AlertCreatedPayload {
  alertId: string;
  encounterId: string;
  patientUnit: string;
  /** Alert severity level */
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  title: string;
  message: string;
  timestamp: string;
}

export interface BedStatusChangedPayload {
  bedId: string;
  patientUnit: string;
  /** New bed status */
  status: 'AVAILABLE' | 'OCCUPIED' | 'CLEANING' | 'MAINTENANCE';
  encounterId?: string;
  timestamp: string;
}

export interface BedSuggestionCreatedPayload {
  /** Agent task unique identifier for the bed suggestion. */
  taskId: string;
  /** Alias used by the backend (snake_case). */
  task_id?: string;
  /** Encrypted / display-safe encounter identifier. */
  encounterId?: string;
  encounter_id?: string;
  /** Encrypted / display-safe patient identifier. */
  patientId?: string;
  patient_id?: string;
  /** Human-readable patient name. */
  patientName?: string;
  patient_name?: string;
  /** Patient acuity level. */
  acuity?: string;
  /** Minutes the patient has been waiting. */
  minutesWaiting?: number;
  minutes_waiting?: number;
  /** Recommended bed identifier. */
  bedId?: string;
  bed_id?: string;
  /** Recommended bed number (display). */
  bestBedNumber?: string;
  best_bed_number?: string;
  /** Unit/floor of the recommended bed. */
  patientUnit?: string;
  patient_unit?: string;
  /** Ranked list of suggested beds (when provided by the backend). */
  suggestions?: Array<{
    bed_id: string;
    bed_number: string;
    unit: string;
    score?: number;
    room?: string;
  }>;
  /** ISO-8601 timestamp of the event. */
  timestamp?: string;
}

export interface BoardingAlertCreatedPayload {
  /** Idempotency key / alert identifier. */
  alertId: string;
  alert_id?: string;
  /** ED encounter identifier. */
  encounterId?: string;
  encounter_id?: string;
  /** ED unit / current location of the patient. */
  patientUnit: string;
  patient_unit?: string;
  /** How long the patient has been waiting in minutes. */
  minutesElapsed: number;
  minutes_elapsed?: number;
  /** Severity classification of the alert. */
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  /** Short headline. */
  title: string;
  /** Human-readable body. */
  message: string;
  /** ISO-8601 timestamp of the event. */
  timestamp?: string;
}

/** Union of all inbound SignalR event payloads */
export type SignalREventPayload =
  | AdtEventPayload
  | TaskUpdatedPayload
  | AlertCreatedPayload
  | BedStatusChangedPayload
  | BedSuggestionCreatedPayload
  | BoardingAlertCreatedPayload;

/** Connection state values mirroring @microsoft/signalr HubConnectionState */
export type SignalRConnectionState =
  | 'Disconnected'
  | 'Connecting'
  | 'Connected'
  | 'Disconnecting'
  | 'Reconnecting';

/** Payload sent to the server's JoinGroups hub method on connect */
export interface JoinGroupsRequest {
  /** Unit IDs the current user belongs to, e.g. ["3A", "3B"] */
  units: string[];
  /** Role names, e.g. ["NURSE", "CHARGE_NURSE"] */
  roles: string[];
}
