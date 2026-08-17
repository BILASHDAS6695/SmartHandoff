/**
 * Physician review alert model.
 *
 * Backend source: app/schemas/physician_alert.py
 * Used by the physician dashboard "Physician Reviews" card and the
 * medication management dialog.
 */
export interface PhysicianAlert {
  id: string;
  encounter_id: string;
  patient_id: string | null;
  alert_type: 'MEDICATION_REVIEW';
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  title: string;
  message: string | null;
  status: 'ACTIVE' | 'RESOLVED';
  metadata?: Record<string, unknown> | null;
  resolved_by_user_id: string | null;
  resolved_at: string | null;
  resolution_type: string | null;
  resolution_note: string | null;
  created_at: string;
}

export interface PhysicianAlertResolveRequest {
  resolution_type: 'REVIEWED_ACCEPTABLE' | 'MEDICATION_UPDATED' | 'MEDICATION_ADDED' | 'DISMISSED';
  resolution_note?: string | null;
}
