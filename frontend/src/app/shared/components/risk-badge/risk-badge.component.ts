import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RiskTier } from '../../models/risk-tier.enum';

/**
 * Displays a colour-coded risk tier badge.
 *
 * Usage: <app-risk-badge [tier]="encounter.risk_tier" />
 *
 * Colours are mapped via CSS custom properties defined in risk-badge.component.scss.
 * All four tiers meet WCAG 2.1 AA contrast ratio (≥4.5:1 for normal text).
 */
@Component({
  selector: 'app-risk-badge',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './risk-badge.component.html',
  styleUrls: ['./risk-badge.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RiskBadgeComponent {
  /** Risk tier value from encounter payload. Defaults to UNSCORED when absent. */
  @Input() tier: RiskTier | string = RiskTier.UNSCORED;

  readonly RiskTier = RiskTier;

  get badgeClass(): string {
    const map: Record<string, string> = {
      [RiskTier.HIGH]: 'risk-badge--high',
      [RiskTier.MEDIUM]: 'risk-badge--medium',
      [RiskTier.LOW]: 'risk-badge--low',
      [RiskTier.UNSCORED]: 'risk-badge--unscored',
    };
    return map[this.tier] ?? 'risk-badge--unscored';
  }

  get ariaLabel(): string {
    const labels: Record<string, string> = {
      [RiskTier.HIGH]: 'High risk',
      [RiskTier.MEDIUM]: 'Medium risk',
      [RiskTier.LOW]: 'Low risk',
      [RiskTier.UNSCORED]: 'Risk not scored',
    };
    return labels[this.tier] ?? 'Risk not scored';
  }
}
