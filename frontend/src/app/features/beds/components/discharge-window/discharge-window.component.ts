/**
 * DischargeWindowComponent — displays predicted discharge time and confidence badge.
 *
 * Design refs:
 *   US-036 AC Scenario 4 — colour-coded confidence indicator
 *   US-036 Technical Notes — high: green; medium: yellow; low: red
 *   NFR-034 — WCAG 2.1 AA; role="status" for screen readers
 */
import {
  ChangeDetectionStrategy,
  Component,
  Input,
  OnChanges,
} from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ConfidenceLevel } from '../../models/bed.model';

interface ConfidenceConfig {
  label: string;
  color: 'primary' | 'accent' | 'warn';
  cssClass: string;
  ariaLabel: string;
}

const CONFIDENCE_MAP: Record<NonNullable<ConfidenceLevel>, ConfidenceConfig> = {
  high: {
    label: 'High Confidence',
    color: 'primary',
    cssClass: 'confidence--high',
    ariaLabel: 'High confidence prediction (within ±1 hour)',
  },
  medium: {
    label: 'Medium Confidence',
    color: 'accent',
    cssClass: 'confidence--medium',
    ariaLabel: 'Medium confidence prediction (within ±2 hours)',
  },
  low: {
    label: 'Low Confidence',
    color: 'warn',
    cssClass: 'confidence--low',
    ariaLabel: 'Low confidence prediction (more than ±2 hours)',
  },
};

@Component({
  selector: 'sh-discharge-window',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, MatChipsModule, MatIconModule, MatTooltipModule, DatePipe],
  template: `
    <div class="discharge-window" role="status" [attr.aria-label]="ariaDescription">
      @if (predictedDischargeTime) {
        <span class="discharge-window__time">
          <mat-icon aria-hidden="true" class="discharge-window__icon">schedule</mat-icon>
          {{ predictedDischargeTime | date:'HH:mm, MMM d' }}
          @if (intervalHours != null) {
            <span class="discharge-window__interval">
              (&plusmn;{{ intervalHours | number:'1.0-1' }}h)
            </span>
          }
        </span>
        @if (confidenceConfig) {
          <mat-chip
            [class]="'confidence-chip ' + confidenceConfig.cssClass"
            [matTooltip]="confidenceConfig.ariaLabel"
            [attr.aria-label]="confidenceConfig.ariaLabel"
            disableRipple
          >
            {{ confidenceConfig.label }}
          </mat-chip>
        }
      } @else {
        <span class="discharge-window__unknown" aria-label="Discharge time not yet predicted">
          <mat-icon aria-hidden="true">hourglass_empty</mat-icon>
          Predicting&hellip;
        </span>
      }
    </div>
  `,
  styles: [`
    .discharge-window {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .discharge-window__time {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 0.875rem;
      font-weight: 500;
    }
    .discharge-window__icon {
      font-size: 1rem;
      height: 1rem;
      width: 1rem;
    }
    .discharge-window__interval {
      font-size: 0.75rem;
      opacity: 0.7;
    }
    .discharge-window__unknown {
      display: flex;
      align-items: center;
      gap: 4px;
      font-size: 0.8rem;
      color: var(--mat-sys-on-surface-variant);
    }
    /* Colour overrides for confidence tiers (WCAG 2.1 AA compliant) */
    .confidence-chip.confidence--high  { background-color: #2e7d32; color: #fff; }
    .confidence-chip.confidence--medium { background-color: #f57f17; color: #fff; }
    .confidence-chip.confidence--low   { background-color: #c62828; color: #fff; }
  `],
})
export class DischargeWindowComponent implements OnChanges {
  @Input() predictedDischargeTime: string | null = null;
  @Input() dischargePredictionConfidence: ConfidenceLevel = null;
  @Input() intervalHours: number | null = null;

  confidenceConfig: ConfidenceConfig | null = null;
  ariaDescription = 'Discharge prediction not available';

  ngOnChanges(): void {
    this.confidenceConfig = this.dischargePredictionConfidence
      ? CONFIDENCE_MAP[this.dischargePredictionConfidence]
      : null;

    if (this.predictedDischargeTime && this.confidenceConfig) {
      this.ariaDescription =
        `Predicted discharge: ${this.predictedDischargeTime}. ${this.confidenceConfig.ariaLabel}`;
    }
  }
}
