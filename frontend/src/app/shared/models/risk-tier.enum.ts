/**
 * Risk stratification tiers as produced by the Follow-up Care Agent
 * (FR-052). Maps directly to the `risk_tier` field on the Encounter API
 * response. All display logic for this enum lives exclusively in RiskBadgeComponent.
 */
export enum RiskTier {
  HIGH = 'HIGH',
  MEDIUM = 'MEDIUM',
  LOW = 'LOW',
  UNSCORED = 'UNSCORED',
}
