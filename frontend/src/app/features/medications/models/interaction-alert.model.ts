/**
 * Interaction alert domain models.
 * Source: US-031 Interaction Alert API
 */

/**
 * Interaction alert as returned by GET /api/v1/alerts/{alertId}.
 */
export interface InteractionAlert {
  alertId: string;
  encounterId: string;
  drug1Name: string;
  drug2Name: string;
  /** First 200 characters of RxNav interaction description */
  descriptionExcerpt: string;
  /** Full description — loaded on "Read more" expansion */
  descriptionFull: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  status: 'OPEN' | 'RESOLVED';
}

/**
 * Resolution payload sent to PATCH /api/v1/alerts/{alertId}/resolve.
 */
export interface AlertResolutionPayload {
  resolutionType: AlertResolutionType;
  /** Optional clinician note, max 500 characters */
  note?: string;
}

export type AlertResolutionType =
  | 'REVIEWED_ACCEPTABLE'
  | 'DOSE_ADJUSTED'
  | 'DRUG_CHANGED'
  | 'DISCONTINUED';
