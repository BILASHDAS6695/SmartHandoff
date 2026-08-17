import { RiskTier } from '../../../shared/models/risk-tier.enum';

/** Encounter-level patient record as returned by GET /api/v1/encounters */
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
  status: string;
  risk_tier: RiskTier;
  risk_score: number | null;
  admission_date: string; // ISO 8601
  updated_at?: string; // ISO 8601
}

/** De-duplicated patient record as returned by GET /api/v1/patients?unique=true */
export interface UniquePatientSummary {
  patient_id: string;
  /** Masked MRN — last 4 digits only, per HIPAA minimum-necessary */
  mrn_masked: string;
  first_name: string;
  last_name: string;
  date_of_birth: string; // ISO 8601
  active_encounter_count: number;
  active_encounter_id: string | null;
  latest_status: string;
  latest_risk_tier: RiskTier;
}

/** Paginated list response envelope */
export interface PatientListResponse {
  items: PatientSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** Paginated unique-patient list response envelope */
export interface UniquePatientListResponse {
  items: UniquePatientSummary[];
  total: number;
  page: number;
  page_size: number;
}

/** Query parameters for GET /api/v1/patients or /api/v1/encounters */
export interface PatientListQuery {
  unit: string;
  search?: string;
  status?: string;
  page?: number;
  page_size?: number;
  unique?: boolean;
  patient_id?: string;
  mrn?: string;
}

/** Detailed patient/encounter record as returned by GET /api/v1/patients/{id} */
export interface PatientDetail {
  encounter_id: string;
  patient_id: string;
  mrn_masked: string;
  first_name: string;
  last_name: string;
  date_of_birth: string;
  current_unit: string;
  room_number: string;
  status: string;
  risk_tier: RiskTier;
  risk_score: number | null;
  admission_date: string;
}
