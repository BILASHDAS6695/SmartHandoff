# TASK-003: BedDetailPanelComponent — Slide-In Panel with RBAC Patient Info and Assign Bed Action

> **Story:** US-050 | **Effort:** 8 hours | **Layer:** Frontend — Component
> **Status:** Draft | **Date:** 2026-07-17

---

## Objective

Build `BedDetailPanelComponent` as a right-side slide-in panel that opens when a bed cell is clicked. The panel displays bed occupancy details with RBAC-controlled patient name visibility (initials for most roles; full name only for `physician` and `charge_nurse`). An "Assign Bed" button is rendered exclusively for `VACANT` beds (SC3).

---

## Context

Bed managers need actionable context when selecting a bed — patient risk tier, predicted discharge time, and assigned nurse — without leaving the floor plan. RBAC enforcement at the component level is required because PHI (full patient name) must only be visible to authorised roles (HIPAA field-level privacy, ADR-007).

**Upstream Dependencies:**
- TASK-001: `BedDto`, `BedCellComponent` click event output, `BedBoardComponent`
- US-036: `riskTier` and `predictedDischargeTime` fields available in `BedDto`
- EP-001: `AuthService.hasRole(roles: string[])` for RBAC name visibility check

---

## Scope

### In Scope

1. **`BedDetailPanelComponent`** — slide-in panel, Angular `@Input() bed: BedDto | null`
2. **RBAC name visibility** — full name shown only when `AuthService.hasRole(['physician', 'charge_nurse'])` returns `true`
3. **Risk tier badge** — `HIGH` (red), `MEDIUM` (amber), `LOW` (green) using Angular Material chip
4. **Assign Bed button** — visible only when `bed.status === 'VACANT'`; emits `(assignBed)` output event
5. **Panel open/close animation** — CSS `transform: translateX` transition (300ms ease-in-out)
6. **Integration into `BedBoardComponent`** — handle `(click)` on `BedCellComponent`, pass selected bed to panel

### Out of Scope

- Actual bed assignment API call (separate story / US-051 or later)
- Unit filter logic (TASK-004)
- Unit tests (TASK-005)

---

## Acceptance Criteria

### AC1: Panel opens on bed cell click
**Given** the bed board is displayed
**When** the bed manager clicks on bed cell `3A-02`
**Then** `BedDetailPanelComponent` slides open from the right; `selectedBed` is set to the clicked `BedDto`; the panel animation completes within 300ms

### AC2: Authorised roles see full patient name
**Given** `AuthService.hasRole(['physician', 'charge_nurse'])` returns `true`
**When** the panel renders for an OCCUPIED bed with `patientName: "John Doe"`
**Then** the panel displays `"John Doe"` (unmasked full name)

### AC3: Unauthorised roles see masked initials
**Given** `AuthService.hasRole(['physician', 'charge_nurse'])` returns `false` (e.g., role is `bed_manager`)
**When** the panel renders for the same OCCUPIED bed
**Then** the panel displays `"J.D."` (masked via `MaskNamePipe`)

### AC4: Risk tier badge displayed correctly
**Given** `bed.riskTier: "HIGH"`
**When** the panel renders
**Then** a red `<mat-chip>` with text `"HIGH RISK"` is displayed; `"MEDIUM"` renders amber; `"LOW"` renders green; `null` shows no badge

### AC5: Assign Bed button visible only for VACANT beds
**Given** `bed.status === 'VACANT'`
**When** the panel renders
**Then** an `"Assign Bed"` `<button mat-raised-button>` is visible and enabled
**Given** `bed.status` is any other value
**Then** the button is hidden (`*ngIf="bed.status === 'VACANT'"`)

### AC6: Panel closes on Escape key or close button
**Given** the panel is open
**When** the user presses `Escape` or clicks the `×` close button
**Then** `selectedBed` is set to `null` and the panel slides closed

---

## Implementation Details

### File: `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.ts`

```typescript
import {
  Component, Input, Output, EventEmitter,
  ChangeDetectionStrategy, inject, HostListener,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatIconModule } from '@angular/material/icon';
import { BedDto } from '../../models/bed.model';
import { MaskNamePipe } from '@shared/pipes/mask-name.pipe';
import { AuthService } from '@core/auth/auth.service';

@Component({
  selector: 'app-bed-detail-panel',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatChipsModule, MatIconModule, MaskNamePipe],
  templateUrl: './bed-detail-panel.component.html',
  styleUrl: './bed-detail-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedDetailPanelComponent {
  private readonly auth = inject(AuthService);

  @Input() bed: BedDto | null = null;
  @Output() closed = new EventEmitter<void>();
  @Output() assignBed = new EventEmitter<BedDto>();

  get isOpen(): boolean { return this.bed !== null; }

  /** Show full name only for physician and charge_nurse roles (RBAC + HIPAA). */
  get patientDisplayName(): string | null {
    if (!this.bed?.patientName) return null;
    return this.auth.hasRole(['physician', 'charge_nurse'])
      ? this.bed.patientName
      : new MaskNamePipe().transform(this.bed.patientName);
  }

  get riskChipClass(): string {
    const map: Record<string, string> = {
      HIGH: 'risk-chip--high',
      MEDIUM: 'risk-chip--medium',
      LOW: 'risk-chip--low',
    };
    return this.bed?.riskTier ? (map[this.bed.riskTier] ?? '') : '';
  }

  close(): void { this.closed.emit(); }

  onAssignBed(): void {
    if (this.bed) this.assignBed.emit(this.bed);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void { if (this.isOpen) this.close(); }
}
```

### File: `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.html`

```html
<aside
  class="bed-detail-panel"
  [class.bed-detail-panel--open]="isOpen"
  role="dialog"
  aria-modal="true"
  [attr.aria-label]="bed ? 'Bed ' + bed.bedId + ' details' : 'Bed details'">

  @if (bed) {
    <header class="bed-detail-panel__header">
      <h2>Bed {{ bed.bedId }}</h2>
      <button mat-icon-button aria-label="Close panel" (click)="close()">
        <mat-icon>close</mat-icon>
      </button>
    </header>

    <div class="bed-detail-panel__body">
      <p class="bed-detail-panel__status">
        Status: <strong>{{ bed.status }}</strong>
      </p>

      @if (bed.status === 'OCCUPIED') {
        <p class="bed-detail-panel__patient">
          Patient: <strong>{{ patientDisplayName ?? '—' }}</strong>
        </p>

        @if (bed.riskTier) {
          <mat-chip [class]="riskChipClass" disableRipple>
            {{ bed.riskTier }} RISK
          </mat-chip>
        }

        <p class="bed-detail-panel__discharge">
          Predicted discharge:
          <strong>
            {{ bed.predictedDischargeTime
               ? (bed.predictedDischargeTime | date:'short')
               : '—' }}
          </strong>
        </p>

        <p class="bed-detail-panel__nurse">
          Assigned nurse: <strong>{{ bed.assignedNurse ?? '—' }}</strong>
        </p>
      }

      @if (bed.status === 'VACANT') {
        <button
          mat-raised-button
          color="primary"
          class="bed-detail-panel__assign-btn"
          (click)="onAssignBed()"
          aria-label="Assign bed {{ bed.bedId }}">
          Assign Bed
        </button>
      }
    </div>
  }
</aside>
```

### File: `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.scss`

```scss
.bed-detail-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 320px;
  height: 100vh;
  background: #ffffff;
  box-shadow: -4px 0 16px rgba(0, 0, 0, 0.12);
  transform: translateX(100%);
  transition: transform 300ms ease-in-out;
  z-index: 1000;
  display: flex;
  flex-direction: column;

  &--open { transform: translateX(0); }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px;
    border-bottom: 1px solid #E0E0E0;
  }

  &__body {
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow-y: auto;
  }

  &__assign-btn { align-self: flex-start; margin-top: 8px; }
}

.risk-chip--high   { background-color: #FFCDD2 !important; color: #B71C1C !important; }
.risk-chip--medium { background-color: #FFE0B2 !important; color: #E65100 !important; }
.risk-chip--low    { background-color: #C8E6C9 !important; color: #1B5E20 !important; }
```

### Modification: `src/app/features/beds/components/bed-board/bed-board.component.ts`

```typescript
// Add to BedBoardComponent:
readonly selectedBed = signal<BedDto | null>(null);

onBedClick(bed: BedDto): void {
  this.selectedBed.set(bed);
}

onPanelClosed(): void {
  this.selectedBed.set(null);
}
```

### Modification: `src/app/features/beds/components/bed-board/bed-board.component.html`

Add below the grid section:

```html
<app-bed-detail-panel
  [bed]="selectedBed()"
  (closed)="onPanelClosed()"
  (assignBed)="onAssignBed($event)">
</app-bed-detail-panel>
```

---

## Files Created

| File | Action |
|------|--------|
| `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.ts` | **Create** |
| `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.html` | **Create** |
| `src/app/features/beds/components/bed-detail-panel/bed-detail-panel.component.scss` | **Create** |

## Files Modified

| File | Change |
|------|--------|
| `src/app/features/beds/components/bed-board/bed-board.component.ts` | Add `selectedBed` signal, `onBedClick()`, `onPanelClosed()` |
| `src/app/features/beds/components/bed-board/bed-board.component.html` | Add `<app-bed-detail-panel>` element |

---

## Validation Checklist

- [ ] Click OCCUPIED bed → panel slides open with patient initials (bed_manager role mock)
- [ ] Switch auth mock to `physician` → full patient name visible
- [ ] Click VACANT bed → "Assign Bed" button visible; `assignBed` event emitted on click
- [ ] Press `Escape` → panel closes; `selectedBed` signal resets to `null`
- [ ] `HIGH` risk tier chip is red; `MEDIUM` amber; `LOW` green; `null` shows no chip
- [ ] Panel animation transition is 300ms (verify in browser Performance tab)
