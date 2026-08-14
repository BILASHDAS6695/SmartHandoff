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
  bedType?: string;
  bedStatus: BedStatus;
  isolationRequired?: boolean;
  genderDesignation?: string;
  encounterId: string | null;
  lastUpdated?: string; // ISO datetime

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

/** Score breakdown for a single bed recommendation. */
export interface BedSuggestionScoreBreakdown {
  acuity_match: number;
  care_type_match: number;
  isolation_match: number;
  gender_match: number;
}

/** A single ranked bed suggestion from the Bed Management Agent. */
export interface RankedBedSuggestion {
  bed_id: string;
  bed_number: string;
  unit: string;
  room: string;
  score: number;
  score_breakdown: BedSuggestionScoreBreakdown;
}

/** Pending bed suggestion returned by GET /api/v1/beds/suggestions. */
export interface BedSuggestion {
  task_id: string;
  encounter_id: string;
  patient_name: string;
  current_unit: string | null;
  acuity: string;
  minutes_waiting: number | null;
  best_bed_id: string;
  best_bed_number: string;
  best_bed_unit: string;
  suggestions: RankedBedSuggestion[];
  created_at: string;
}

/** Occupant details for an occupied bed (GET /api/v1/beds/{id}/details). */
export interface BedOccupant {
  encounter_id: string;
  patient_id: string;
  first_name: string;
  last_name: string;
  date_of_birth: string | null;
  mrn_masked: string;
  encounter_status: string;
  unit: string | null;
  risk_tier: string;
  admission_date: string | null;
}

/** A patient waiting for bed allocation, shown when a bed is selected. */
export interface WaitingPatientForBed {
  task_id: string;
  encounter_id: string;
  patient_name: string;
  current_unit: string | null;
  acuity: string;
  minutes_waiting: number | null;
  best_bed_id: string;
  best_bed_number: string;
  best_bed_unit: string;
}

/** AI medication analysis snapshot embedded in bed details. */
export interface MedicationAnalysisSnapshot {
  readmission_risk: string;
  confidence: string;
  safety_score: number;
  summary: string;
  risks: string[];
  recommendations: string[];
  predicted_issues: string[];
}

/** Detailed bed response including occupant and waiting patients. */
export interface BedDetailDto {
  bed_id: string;
  bed_number: string;
  unit: string;
  room: string | null;
  bed_type: string;
  status: BedStatus;
  isolation_required: boolean;
  gender_designation: string;
  predicted_discharge_time: string | null;
  occupant: BedOccupant | null;
  waiting_patients: WaitingPatientForBed[];
  medication_analysis: MedicationAnalysisSnapshot | null;
}
