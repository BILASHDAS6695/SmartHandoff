import { RiskTier } from '@shared/models/risk-tier.enum';

/**
 * Payload of the `risk_score_updated` SignalR event emitted by the
 * FastAPI hub when the Follow-up Care Agent recalculates a patient's
 * risk tier.
 */
export interface RiskScoreUpdatedEvent {
  encounter_id: string;
  risk_tier: RiskTier;
  risk_score: number;
  updated_at: string; // ISO 8601
}
