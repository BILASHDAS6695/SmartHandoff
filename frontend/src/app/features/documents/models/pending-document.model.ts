/**
 * Document approval queue domain models.
 * Source: US-025 Document API
 */

/**
 * Document awaiting physician approval.
 */
export interface PendingDocument {
  documentId: string;
  encounterId: string;
  patientName: string;
  documentType: 'DISCHARGE_SUMMARY' | 'PATIENT_INSTRUCTIONS' | 'REFERRAL';
  generatedAt: string; // ISO 8601
  status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED';
  /** AI-generated content excerpt (first 200 chars) */
  contentExcerpt: string;
}

export interface DocumentActionPayload {
  action: 'APPROVED' | 'REJECTED';
  /** Optional rejection reason, required when action = REJECTED */
  rejectionReason?: string;
}
