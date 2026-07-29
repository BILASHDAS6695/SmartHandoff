/**
 * TypeScript interfaces for all SignalR event payloads from the FastAPI backend.
 * Each interface maps 1:1 to a server-sent event type.
 *
 * US-048: Integrate SignalR for Real-Time Dashboard Updates
 */

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
  taskId: string;
  encounterId: string;
  /** Task type label, e.g. "Documentation Agent" */
  taskName: string;
  /** Previous task status */
  previousStatus: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  /** New task status */
  newStatus: 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'FAILED';
  /** ISO-8601 completion timestamp (present only when newStatus === 'COMPLETED') */
  completedAt?: string;
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

/** Union of all inbound SignalR event payloads */
export type SignalREventPayload =
  | AdtEventPayload
  | TaskUpdatedPayload
  | AlertCreatedPayload
  | BedStatusChangedPayload;

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
