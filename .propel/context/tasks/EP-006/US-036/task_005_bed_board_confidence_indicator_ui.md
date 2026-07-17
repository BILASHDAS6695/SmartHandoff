---
id: TASK-005
title: "Bed Board UI — Predicted Discharge Time and Confidence Indicator Component"
user_story: US-036
epic: EP-006
sprint: 2
layer: Frontend
estimate: 3h
priority: Must Have
status: Draft
date: 2026-07-17
assignee: Frontend Engineer
upstream: [US-036/TASK-003, US-035/TASK-005]
---

# TASK-005: Bed Board UI — Predicted Discharge Time and Confidence Indicator Component

> **Story:** US-036 | **Epic:** EP-006 | **Sprint:** 2 | **Layer:** Frontend | **Est:** 3 h
> **Status:** Draft | **Date:** 2026-07-17

---

## Context

US-036 AC Scenario 4 requires the Angular bed board to display the `predicted_discharge_time` for each occupied bed alongside a colour-coded confidence indicator:

- **Green** — `high` confidence (std_dev < 1 h)
- **Yellow** — `medium` confidence (std_dev 1–2 h)
- **Red** — `low` confidence (std_dev > 2 h)

The bed board feature module (`features/beds/`) was established by US-035/TASK-005. This task extends the `BedCardComponent` with a `DischargeWindowComponent` sub-component and updates the `BedItem` model and API client to include prediction fields.

**Design references:**
- US-036 AC Scenario 4 — predicted discharge time + colour-coded confidence indicator
- US-036 Technical Notes — confidence thresholds: high <1 h, medium 1-2 h, low >2 h
- design.md §3.4 — `features/beds/` lazy-loaded feature module; `BedCardComponent`
- design.md §4.1 (Angular Material 17) — WCAG 2.1 AA; Angular Material for colour chip
- design.md §5.1 (NFR-034) — WCAG 2.1 AA accessibility compliance
- design.md §5.1 (NFR-006) — SignalR push latency <1 s; prediction refresh via SignalR

---

## Acceptance Criteria Addressed

| AC Scenario | Coverage |
|-------------|----------|
| Scenario 4 | Bed board shows `predicted_discharge_time` + colour-coded confidence indicator for bed `3A-01` |

---

## Implementation Steps

### 1. Update `BedItem` model interface

In `src/app/features/beds/models/bed.model.ts`:

```typescript
/**
 * Represents a single bed entry from the mv_bed_board API response.
 * Prediction fields are nullable (null when no admitted encounter or no prediction yet).
 *
 * Design refs:
 *   US-036 AC Scenario 4 — predicted_discharge_time + confidence_level on bed board
 *   US-036 Technical Notes — confidence tiers: 'high' | 'medium' | 'low'
 */
export type ConfidenceLevel = 'high' | 'medium' | 'low' | null;

export interface BedItem {
  bedId: string;
  unit: string;
  room: string;
  bedNumber: string;
  bedStatus: 'VACANT' | 'OCCUPIED' | 'DIRTY' | 'MAINTENANCE' | 'RESERVED';
  encounterId: string | null;
  lastUpdated: string; // ISO datetime

  // US-036 prediction fields
  predictedDischargeTime: string | null;          // ISO datetime UTC
  dischargePredictionConfidence: ConfidenceLevel; // 'high' | 'medium' | 'low' | null
  dischargePredictionIntervalHours: number | null; // ±hours
}
```

### 2. Update `BedsApiService` to map new prediction fields

In `src/app/features/beds/services/beds-api.service.ts`:

```typescript
// In the mapBedResponse private method, add:
predictedDischargeTime: raw['predicted_discharge_time'] ?? null,
dischargePredictionConfidence: raw['discharge_prediction_confidence'] ?? null,
dischargePredictionIntervalHours: raw['discharge_prediction_interval_hours'] ?? null,
```

### 3. Create `DischargeWindowComponent`

```bash
ng generate component features/beds/components/discharge-window \
  --standalone --skip-tests
```

**`src/app/features/beds/components/discharge-window/discharge-window.component.ts`:**

```typescript
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
          <span class="discharge-window__interval" *ngIf="intervalHours != null">
            (&plusmn;{{ intervalHours | number:'1.0-1' }}h)
          </span>
        </span>
        <mat-chip
          *ngIf="confidenceConfig"
          [class]="'confidence-chip ' + confidenceConfig.cssClass"
          [matTooltip]="confidenceConfig.ariaLabel"
          [attr.aria-label]="confidenceConfig.ariaLabel"
          disableRipple
        >
          {{ confidenceConfig.label }}
        </mat-chip>
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
    /* Colour overrides for confidence tiers */
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
```

### 4. Integrate `DischargeWindowComponent` into `BedCardComponent`

In `src/app/features/beds/components/bed-card/bed-card.component.ts`:

```typescript
// Add to imports array:
import { DischargeWindowComponent } from '../discharge-window/discharge-window.component';

// Add to @Component imports:
imports: [..., DischargeWindowComponent],
```

In `bed-card.component.html`, inside the occupied bed section:

```html
<!-- Show prediction only for OCCUPIED beds -->
@if (bed.bedStatus === 'OCCUPIED') {
  <sh-discharge-window
    [predictedDischargeTime]="bed.predictedDischargeTime"
    [dischargePredictionConfidence]="bed.dischargePredictionConfidence"
    [intervalHours]="bed.dischargePredictionIntervalHours"
  />
}
```

### 5. Handle SignalR real-time updates for prediction refresh

In `src/app/features/beds/services/bed-board-signalr.service.ts` — the existing SignalR handler already updates the full `BedItem` via the `bedUpdated` event. Verify that:

- The `bedUpdated` SignalR event payload from the backend includes the three prediction fields.
- The beds state is updated via the existing `@ngrx/signals` store or `BehaviorSubject` so Angular re-renders the `DischargeWindowComponent` automatically.
- No additional SignalR event handler is needed.

If the backend SignalR payload omits prediction fields, update `SignalRHubService.mapBedUpdatedEvent()` to include them — matching Step 2 field mapping.

### 6. Add ARIA and keyboard accessibility

Verify in the template:
- `role="status"` on the `.discharge-window` div (live region for screen readers on real-time updates)
- `aria-label` on the confidence chip describes the confidence tier in plain language
- Colour is not the sole indicator — text label is also present inside the chip (WCAG 1.4.1)
- Contrast ratios meet WCAG 2.1 AA (4.5:1 for text; verified via axe-core in CI)

### 7. Run axe-core accessibility check

```bash
# In CI — angular-eslint + axe-core integration
ng lint
npx axe-core --url http://localhost:4200/beds
```

---

## Validation Checklist

- [ ] `DischargeWindowComponent` renders predicted discharge time in `HH:mm, MMM d` format
- [ ] Green chip for `high` confidence, yellow for `medium`, red for `low`
- [ ] Null `predictedDischargeTime` renders "Predicting…" with an hourglass icon (not blank)
- [ ] Colour chip also includes a text label (WCAG 1.4.1 — not colour alone)
- [ ] `role="status"` on the container div (screen reader announces on update)
- [ ] `@if (bed.bedStatus === 'OCCUPIED')` guard — VACANT/DIRTY beds show no prediction widget
- [ ] SignalR update refreshes the component without page reload
- [ ] `ng build --configuration production` completes with no errors or WCAG axe violations
- [ ] Tested with `discharge_prediction_confidence = null` — renders "Predicting…" gracefully

---

## Definition of Done Checklist (US-036)

| Item | Status |
|------|--------|
| ✅ Prediction displayed on bed board with colour-coded confidence indicator (AC Scenario 4) | This task |
