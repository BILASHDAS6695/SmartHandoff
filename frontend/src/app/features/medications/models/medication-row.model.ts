/**
 * Medication reconciliation domain models.
 * Source: US-030 Medication Reconciliation API
 */

/**
 * Represents a single medication row in the reconciliation view.
 * Populated from the Medication Reconciliation API (US-030).
 */
export interface MedicationRow {
  /** Unique medication identifier from FHIR MedicationRequest.id */
  id: string;
  drugName: string;
  dose: string;
  frequency: string;
  /** Interaction severity for this drug. Null when no interaction detected. */
  interactionSeverity: InteractionSeverity | null;
  /** ID of the interaction alert, used to open resolution modal */
  alertId: string | null;
}

export type InteractionSeverity = 'HIGH' | 'MEDIUM' | 'LOW' | null;

/**
 * Three-panel reconciliation payload from GET /api/v1/patients/{id}/medications/reconciliation.
 */
export interface MedicationReconciliation {
  encounterId: string;
  preAdmit: MedicationRow[];
  inpatient: MedicationRow[];
  discharge: MedicationRow[];
}
