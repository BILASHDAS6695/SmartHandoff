/**
 * Models for the medication reconciliation review view (SCR-005).
 */

/** Flag type shown in the Discharge Rx column. */
export type MedReviewFlag = 'OK' | 'INTERACT' | 'MISSING' | 'RESOLVED' | 'OMITTED' | 'FLAGGED';

/** A medication row in one of the three reconciliation columns. */
export interface MedReviewRow {
  id: string;
  drugName: string;
  dose: string;
  frequency: string;
  flag?: MedReviewFlag;
  /** Whether this row is a missing-medication banner instead of a regular row. */
  isMissingBanner?: boolean;
  /** Human-readable missing-med reason (e.g. chronic medication). */
  missingReason?: string;
}

/** Active alert shown below the medication table. */
export interface MedReviewAlert {
  id: string;
  type: 'critical' | 'warning';
  title: string;
  body: string;
  primaryAction: string;
  /** Button style for the primary action (matches the wireframe button palette). */
  primaryActionClass?: 'primary' | 'info' | 'secondary';
  secondaryActions: string[];
}

/** Three-panel medication reconciliation payload. */
export interface MedReviewReconciliation {
  encounterId: string;
  patientName: string;
  preAdmit: MedReviewRow[];
  inpatient: MedReviewRow[];
  discharge: MedReviewRow[];
  alerts: MedReviewAlert[];
}
