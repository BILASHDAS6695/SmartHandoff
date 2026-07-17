# TASK-004: Unit Filter (MatButtonToggle + sessionStorage) and WCAG Accessibility

> **Story:** US-050 | **Effort:** 8 hours | **Layer:** Frontend — UX/A11y
> **Status:** Draft | **Date:** 2026-07-17

---

## Objective

Implement the unit filter toolbar using Angular Material `MatButtonToggleGroup` so the bed manager can restrict the floor plan to a single hospital unit (SC4). The selected unit must persist to `sessionStorage` and be restored on navigation return. Ensure every bed cell carries a valid WCAG 2.2 Level AA `aria-label` and the grid degrades gracefully to a list view at 1024px viewports.

---

## Context

The hospital has units `3A`, `3B`, `4A`, `4B`, `ICU`. A bed manager monitoring ICU should not be distracted by surgical ward beds. Persistence via `sessionStorage` (not `localStorage`) limits the filter scope to the active browser tab session — appropriate for a shared clinical workstation environment. WCAG compliance is mandatory per web-accessibility-standards instructions and the DoD for US-050.

**Upstream Dependencies:**
- TASK-001: `BedBoardComponent`, `BedDto.unit` field, `BedCellComponent` `aria-label` method
- UI-003: Healthcare colour palette for active/inactive toggle states
- NFR-034: WCAG 2.1 AA (Angular Material built-in accessibility)

---

## Scope

### In Scope

1. **Unit filter toolbar** — `MatButtonToggleGroup` with `All | 3A | 3B | 4A | 4B | ICU` options, placed above the bed grid
2. **Computed filtered beds** — Angular `computed()` signal deriving visible beds from `beds()` and `selectedUnit()`
3. **`sessionStorage` persistence** — save/restore `bedboard_unit_filter` key on unit change and component init
4. **WCAG `aria-label`** — verify and complete `BedCellComponent.ariaLabel` getter (from TASK-001); validate with axe-core during dev
5. **Responsive breakpoint** — confirm `@media (max-width: 1023px)` list-view SCSS from TASK-001 applies; add `overflow-x: auto` to grid container for intermediate widths

### Out of Scope

- SignalR integration (TASK-002)
- Side panel (TASK-003)
- Unit tests (TASK-005)

---

## Acceptance Criteria

### AC1: Unit filter renders correct options
**Given** the bed board page loads
**When** the toolbar renders
**Then** a `MatButtonToggleGroup` displays buttons: `All`, `3A`, `3B`, `4A`, `4B`, `ICU`; `All` is selected by default if no `sessionStorage` value exists

### AC2: Selecting a unit filters the grid
**Given** the bed board is showing all beds
**When** the bed manager selects `ICU`
**Then** only beds where `bed.unit === 'ICU'` are rendered; all other beds are removed from the DOM

### AC3: Filter persists across navigation
**Given** the bed manager selects unit `3A`
**When** they navigate to the patient list and return to the bed board
**Then** `sessionStorage.getItem('bedboard_unit_filter')` returns `"3A"` and the filter is pre-selected on component init

### AC4: `All` option shows every bed
**Given** `sessionStorage` holds `bedboard_unit_filter: "ICU"`
**When** the bed manager clicks `All`
**Then** all beds are displayed and `sessionStorage` is updated to `"ALL"`

### AC5: Every bed cell has a valid `aria-label`
**Given** bed `3A-02` is OCCUPIED with patient `"J.D."`, discharge predicted `"3:00 PM"`
**When** the cell is rendered
**Then** `aria-label="Bed 3A-02, status Occupied, patient J.D., discharge predicted 3:00 PM"` is present on the element

### AC6: List-view at 1024px viewport
**Given** the browser viewport is set to 1024px width
**When** the bed board renders
**Then** the grid switches to `grid-template-columns: 1fr` (single-column list view); bed cells stack vertically; no horizontal overflow

---

## Implementation Details

### Modification: `src/app/features/beds/components/bed-board/bed-board.component.ts`

```typescript
import { computed, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';

// Session storage key constant
private static readonly UNIT_FILTER_KEY = 'bedboard_unit_filter';

/** All unique units derived from the loaded bed list. */
readonly availableUnits = computed(() =>
  ['ALL', ...new Set(this.beds().map(b => b.unit)).values()]
);

/** Currently selected unit filter; restored from sessionStorage on init. */
readonly selectedUnit = signal<string>(
  sessionStorage.getItem(BedBoardComponent.UNIT_FILTER_KEY) ?? 'ALL'
);

/** Beds filtered by selectedUnit — the source for the template grid. */
readonly filteredBeds = computed(() => {
  const unit = this.selectedUnit();
  return unit === 'ALL'
    ? this.beds()
    : this.beds().filter(b => b.unit === unit);
});

onUnitFilterChange(unit: string): void {
  this.selectedUnit.set(unit);
  sessionStorage.setItem(BedBoardComponent.UNIT_FILTER_KEY, unit);
}
```

Add `MatButtonToggleModule` to `imports` array in `@Component` decorator.

### Modification: `src/app/features/beds/components/bed-board/bed-board.component.html`

Replace `@for (bed of beds()` with `@for (bed of filteredBeds()` and add toolbar above the grid:

```html
<!-- Unit filter toolbar -->
<div class="bed-board__toolbar" role="toolbar" aria-label="Filter beds by unit">
  <mat-button-toggle-group
    [value]="selectedUnit()"
    (change)="onUnitFilterChange($event.value)"
    aria-label="Unit filter">
    @for (unit of availableUnits(); track unit) {
      <mat-button-toggle [value]="unit" [attr.aria-pressed]="selectedUnit() === unit">
        {{ unit }}
      </mat-button-toggle>
    }
  </mat-button-toggle-group>
</div>

<!-- Filtered bed grid -->
@if (!loading() && !error()) {
  <div class="bed-board__grid" role="grid" aria-label="Bed board floor plan">
    @for (bed of filteredBeds(); track bed.bedId) {
      <app-bed-cell
        [bed]="bed"
        (click)="onBedClick(bed)"
        (keydown.enter)="onBedClick(bed)">
      </app-bed-cell>
    }
    @if (filteredBeds().length === 0) {
      <p class="bed-board__empty" role="status">
        No beds found for unit {{ selectedUnit() }}.
      </p>
    }
  </div>
}
```

### WCAG `aria-label` — `BedCellComponent.ariaLabel` (complete implementation)

Ensure `BedCellComponent.ariaLabel` produces compliant output for all states:

```typescript
get ariaLabel(): string {
  const status = this.bed.status.charAt(0) + this.bed.status.slice(1).toLowerCase();
  const patient = this.bed.patientName
    ? `, patient ${new MaskNamePipe().transform(this.bed.patientName)}`
    : '';
  const discharge = this.bed.predictedDischargeTime
    ? `, discharge predicted ${new Date(this.bed.predictedDischargeTime)
        .toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : '';
  return `Bed ${this.bed.bedId}, status ${status}${patient}${discharge}`;
}
```

### Modification: `src/app/features/beds/components/bed-board/bed-board.component.scss`

Add toolbar styles and overflow guard:

```scss
.bed-board__toolbar {
  padding: 8px 16px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.bed-board__grid {
  // existing styles from TASK-001 …
  overflow-x: auto;  // prevent horizontal scroll on intermediate widths
}

.bed-board__empty {
  grid-column: 1 / -1;
  padding: 24px;
  text-align: center;
  color: #757575;
}
```

---

## Files Modified

| File | Change |
|------|--------|
| `src/app/features/beds/components/bed-board/bed-board.component.ts` | Add `selectedUnit`, `filteredBeds`, `availableUnits` signals; `onUnitFilterChange()`; import `MatButtonToggleModule` |
| `src/app/features/beds/components/bed-board/bed-board.component.html` | Add unit filter toolbar; replace `beds()` with `filteredBeds()` in `@for` |
| `src/app/features/beds/components/bed-board/bed-board.component.scss` | Add toolbar styles; add `overflow-x: auto` to grid |
| `src/app/features/beds/components/bed-cell/bed-cell.component.ts` | Complete `ariaLabel` getter with all status/patient/discharge states |

---

## Validation Checklist

- [ ] `All` toggle selected by default on first load
- [ ] Select `ICU` → only ICU beds visible; select `All` → all beds return
- [ ] Navigate to `/patients`, return to `/beds` → `ICU` filter still active
- [ ] Inspect DOM: every `app-bed-cell` has non-empty `aria-label` matching template
- [ ] Run axe-core dev extension: zero critical/serious WCAG violations on bed board route
- [ ] Resize to 1024px: beds stack in single column with no horizontal scrollbar on page
- [ ] Resize to 2560px: beds fill available width in auto-fill columns
