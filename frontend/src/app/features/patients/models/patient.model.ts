import { RiskTier } from '../../../shared/models/risk-tier.enum';

/** Encounter-level patient record as returned by GET /api/v1/patients */
export interface PatientSummary {
  encounter_id: string;
  patient_id: string;
  /** Masked MRN — last 4 digits only, per HIPAA minimum-necessary */
  mrn_masked: string;
  first_name: string;
  last_name: string;
  date_of_birth: string; // ISO 8601
  current_unit: string;
  room_number: string;
  risk_tier: RiskTier;
  risk_score: number | null;
  admission_date: string; // ISO 8601
}

/** Paginated list response envelope */
export interface PatientListResponse {
  items: PatientSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** Query parameters for GET /api/v1/patients */
export interface PatientListQuery {
  unit: string;
  search?: string;
  page?: number;
  page_size?: number;
}
