/**
 * Represents a single bed entry from the mv_bed_board API response.
 * Prediction fields are nullable (null when no admitted encounter or no prediction yet).
 *
 * Design refs:
 *   US-036 AC Scenario 4 — predicted_discharge_time + confidence_level on bed board
 *   US-036 Technical Notes — confidence tiers: 'high' | 'medium' | 'low'
 *   US-050 — Bed board UI with colour-coded status and real-time updates
 */

export type BedStatus = 'VACANT' | 'OCCUPIED' | 'DIRTY' | 'MAINTENANCE' | 'RESERVED';

export type ConfidenceLevel = 'high' | 'medium' | 'low' | null;

export interface BedItem {
  bedId: string;
  unit: string;
  room: string;
  bedNumber: string;
  bedStatus: BedStatus;
  encounterId: string | null;
  lastUpdated: string; // ISO datetime

  // US-036 prediction fields
  predictedDischargeTime: string | null;          // ISO datetime UTC
  dischargePredictionConfidence: ConfidenceLevel; // 'high' | 'medium' | 'low' | null
  dischargePredictionIntervalHours: number | null; // ±hours
}

/**
 * Bed data transfer object for the BedBoardComponent.
 * Simplified view optimised for UI rendering (US-050).
 */
export interface BedDto {
  bedId: string;
  unit: string;
  status: BedStatus;
  patientName: string | null;
  predictedDischargeTime: string | null;
  assignedNurse: string | null;
  riskTier: 'HIGH' | 'MEDIUM' | 'LOW' | null;
}

/**
 * Payload received from SignalR bed_status_changed event (US-050 TASK-002).
 * Consumed by BedRealtimeService to update cell state.
 */
export interface BedUpdateEvent {
  bedId: string;
  status: BedStatus;
  patientName: string | null;
  predictedDischargeTime: string | null;
}

/**
 * Colour token map keyed by BedStatus.
 * Maps status values to CSS class names for styling (US-050 AC2).
 */
export const BED_STATUS_CLASS: Record<BedStatus, string> = {
  VACANT:      'bed-status--vacant',
  OCCUPIED:    'bed-status--occupied',
  DIRTY:       'bed-status--dirty',
  MAINTENANCE: 'bed-status--maintenance',
  RESERVED:    'bed-status--reserved',
};
