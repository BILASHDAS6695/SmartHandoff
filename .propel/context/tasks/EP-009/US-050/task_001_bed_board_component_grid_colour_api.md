# TASK-001: BedBoardComponent — CSS Grid Layout, Colour Map, and Beds API Integration

> **Story:** US-050 | **Effort:** 12 hours | **Layer:** Frontend — Component
> **Status:** Draft | **Date:** 2026-07-17

---

## Objective

Scaffold the `BedBoardComponent` as a standalone Angular component featuring a responsive CSS Grid floor plan, a typed `BedStatus` colour map, and full integration with `GET /api/v1/beds?include_predictions=true`. Skeleton loaders must be rendered during initial data fetch (UI-007).

---

## Context

This is the foundational task for US-050. All other tasks (TASK-002 through TASK-004) depend on the component state model and the `BedDto` interface defined here. The bed board is the primary operational view for Coordinator Carol (BRD §6.5, FR-041), replacing manual phone calls with a self-updating floor plan.

**Upstream Dependencies:**
- US-047: Angular feature module scaffold and lazy routing infrastructure
- US-035: `GET /api/v1/beds` endpoint backed by `mv_bed_board` materialised view
- UI-003: Healthcare colour palette (greens/blues for neutral states; red/amber for alerts)
- UI-007: Skeleton loaders for all async content panels

---

## Scope

### In Scope

1. **`BedDto` interface and `BedStatus` enum** — `src/app/features/beds/models/bed.model.ts`
2. **`BedBoardService`** — `src/app/features/beds/services/bed-board.service.ts`
3. **`BedBoardComponent`** — `src/app/features/beds/components/bed-board/`
4. **`BedCellComponent`** — `src/app/features/beds/components/bed-cell/`
5. **Lazy route registration** — `src/app/features/beds/beds.routes.ts`
6. **`MaskNamePipe`** — `src/app/shared/pipes/mask-name.pipe.ts`

### Out of Scope

- SignalR event subscription (TASK-002)
- `BedDetailPanelComponent` (TASK-003)
- Unit filter and responsive breakpoints (TASK-004)
- Unit tests (TASK-005)

---

## Acceptance Criteria

### AC1: Bed model and service defined
**Given** `GET /api/v1/beds?include_predictions=true` returns a list of beds
**When** `BedBoardService.getBeds()` is called
**Then** it returns `Observable<BedDto[]>` with all fields typed, including `predictedDischargeTime: string | null`

### AC2: Grid renders all beds with correct colour coding
**Given** the `BedBoardComponent` receives a non-empty `BedDto[]`
**When** the component renders
**Then** each bed cell has the CSS class matching `BedStatus`:
- `VACANT` → `bed-status--vacant` (green `#2E7D32`)
- `OCCUPIED` → `bed-status--occupied` (blue `#1565C0`)
- `DIRTY` → `bed-status--dirty` (orange `#E65100`)
- `MAINTENANCE` → `bed-status--maintenance` (grey `#546E7A`)
- `RESERVED` → `bed-status--reserved` (purple `#6A1B9A`)

### AC3: Discharge prediction rendered in each cell
**Given** a bed has `predictedDischargeTime: "2026-07-17T15:00:00Z"`
**When** the bed cell is rendered
**Then** the cell displays the formatted time (e.g., "3:00 PM") below the bed number; if `null`, a `—` dash is shown

### AC4: Patient name masked to initials for all roles
**Given** a bed is OCCUPIED with `patientName: "John Doe"`
**When** the cell renders for any role
**Then** the `MaskNamePipe` transforms the name to `"J.D."` (first initial + last initial)

### AC5: Skeleton loaders shown during initial load
**Given** the component has just mounted and `getBeds()` has not yet resolved
**When** the view renders
**Then** 12 `<mat-card>` skeleton cells (Angular Material skeleton) are displayed with animation; no error state is shown

### AC6: Grid layout uses CSS Grid auto-fill
**Given** the component has loaded bed data
**When** rendered at any viewport between 1024px and 2560px
**Then** the grid container uses `grid-template-columns: repeat(auto-fill, minmax(120px, 1fr))`

---

## Implementation Details

### File: `src/app/features/beds/models/bed.model.ts`

```typescript
/**
 * Bed data transfer object returned by GET /api/v1/beds.
 * Maps directly to the mv_bed_board materialised view.
 */
export type BedStatus = 'VACANT' | 'OCCUPIED' | 'DIRTY' | 'MAINTENANCE' | 'RESERVED';

export interface BedDto {
  bedId: string;          // e.g. "3A-02"
  unit: string;           // e.g. "3A", "ICU"
  status: BedStatus;
  patientName: string | null;
  predictedDischargeTime: string | null;  // ISO-8601 UTC, from mv_bed_board
  assignedNurse: string | null;
  riskTier: 'HIGH' | 'MEDIUM' | 'LOW' | null;
}

/** Payload received from SignalR bed_status_changed event (consumed by TASK-002). */
export interface BedUpdateEvent {
  bedId: string;
  status: BedStatus;
  patientName: string | null;
  predictedDischargeTime: string | null;
}

/** Colour token map keyed by BedStatus. */
export const BED_STATUS_CLASS: Record<BedStatus, string> = {
  VACANT:      'bed-status--vacant',
  OCCUPIED:    'bed-status--occupied',
  DIRTY:       'bed-status--dirty',
  MAINTENANCE: 'bed-status--maintenance',
  RESERVED:    'bed-status--reserved',
};
```

### File: `src/app/features/beds/services/bed-board.service.ts`

```typescript
import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { BedDto } from '../models/bed.model';
import { environment } from '@environments/environment';

@Injectable({ providedIn: 'root' })
export class BedBoardService {
  private readonly http = inject(HttpClient);
  private readonly apiBase = `${environment.apiUrl}/api/v1/beds`;

  getBeds(includePredictions = true): Observable<BedDto[]> {
    const params = new HttpParams().set('include_predictions', String(includePredictions));
    return this.http.get<BedDto[]>(this.apiBase, { params });
  }
}
```

### File: `src/app/shared/pipes/mask-name.pipe.ts`

```typescript
import { Pipe, PipeTransform } from '@angular/core';

/** Transforms a full patient name to initials (e.g., "John Doe" → "J.D."). */
@Pipe({ name: 'maskName', standalone: true })
export class MaskNamePipe implements PipeTransform {
  transform(fullName: string | null): string {
    if (!fullName) return '—';
    return fullName
      .trim()
      .split(/\s+/)
      .filter(Boolean)
      .map(part => `${part.charAt(0).toUpperCase()}.`)
      .join('');
  }
}
```

### File: `src/app/features/beds/components/bed-cell/bed-cell.component.ts`

```typescript
import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { BedDto, BED_STATUS_CLASS } from '../../models/bed.model';
import { MaskNamePipe } from '@shared/pipes/mask-name.pipe';

@Component({
  selector: 'app-bed-cell',
  standalone: true,
  imports: [CommonModule, MatCardModule, MaskNamePipe],
  templateUrl: './bed-cell.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedCellComponent {
  @Input({ required: true }) bed!: BedDto;

  get statusClass(): string {
    return BED_STATUS_CLASS[this.bed.status];
  }

  get ariaLabel(): string {
    const name = this.bed.patientName
      ? `, patient ${new MaskNamePipe().transform(this.bed.patientName)}`
      : '';
    const discharge = this.bed.predictedDischargeTime
      ? `, discharge predicted ${new Date(this.bed.predictedDischargeTime).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
      : '';
    return `Bed ${this.bed.bedId}, status ${this.bed.status}${name}${discharge}`;
  }
}
```

### File: `src/app/features/beds/components/bed-cell/bed-cell.component.html`

```html
<mat-card
  class="bed-cell"
  [ngClass]="statusClass"
  [attr.aria-label]="ariaLabel"
  role="button"
  tabindex="0">
  <span class="bed-cell__id">{{ bed.bedId }}</span>
  <span class="bed-cell__patient">{{ bed.patientName | maskName }}</span>
  <span class="bed-cell__discharge">
    {{ bed.predictedDischargeTime
       ? (bed.predictedDischargeTime | date:'shortTime')
       : '—' }}
  </span>
</mat-card>
```

### File: `src/app/features/beds/components/bed-board/bed-board.component.ts`

```typescript
import { Component, OnInit, signal, inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { BedBoardService } from '../../services/bed-board.service';
import { BedCellComponent } from '../bed-cell/bed-cell.component';
import { BedDto } from '../../models/bed.model';

@Component({
  selector: 'app-bed-board',
  standalone: true,
  imports: [CommonModule, BedCellComponent, MatProgressSpinnerModule],
  templateUrl: './bed-board.component.html',
  styleUrl: './bed-board.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BedBoardComponent implements OnInit {
  private readonly bedService = inject(BedBoardService);

  readonly beds = signal<BedDto[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  /** Exposed for TASK-002 SignalR handler to update individual cells. */
  updateBedStatus(bedId: string, patch: Partial<BedDto>): void {
    this.beds.update(current =>
      current.map(b => (b.bedId === bedId ? { ...b, ...patch } : b))
    );
  }

  ngOnInit(): void {
    this.bedService.getBeds().subscribe({
      next: data => {
        this.beds.set(data);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Unable to load bed board. Please refresh.');
        this.loading.set(false);
      },
    });
  }
}
```

### File: `src/app/features/beds/components/bed-board/bed-board.component.html`

```html
<!-- Skeleton loaders: shown while loading (UI-007) -->
@if (loading()) {
  <div class="bed-board__grid" aria-busy="true" aria-label="Loading bed board">
    @for (i of [1,2,3,4,5,6,7,8,9,10,11,12]; track i) {
      <div class="bed-cell bed-cell--skeleton"></div>
    }
  </div>
}

<!-- Error state -->
@if (error()) {
  <p class="bed-board__error" role="alert">{{ error() }}</p>
}

<!-- Bed grid (rendered by TASK-004 with unit filter wrapper) -->
@if (!loading() && !error()) {
  <div class="bed-board__grid" role="grid" aria-label="Bed board floor plan">
    @for (bed of beds(); track bed.bedId) {
      <app-bed-cell
        [bed]="bed"
        (click)="onBedClick(bed)"
        (keydown.enter)="onBedClick(bed)">
      </app-bed-cell>
    }
  </div>
}
```

### File: `src/app/features/beds/components/bed-board/bed-board.component.scss`

```scss
// CSS Grid floor plan layout — responsive from 1024px to 2560px.
.bed-board__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
  padding: 16px;
}

// Status colour tokens (UI-003 healthcare palette).
.bed-status--vacant      { --bed-bg: #E8F5E9; --bed-border: #2E7D32; }
.bed-status--occupied    { --bed-bg: #E3F2FD; --bed-border: #1565C0; }
.bed-status--dirty       { --bed-bg: #FBE9E7; --bed-border: #E65100; }
.bed-status--maintenance { --bed-bg: #ECEFF1; --bed-border: #546E7A; }
.bed-status--reserved    { --bed-bg: #F3E5F5; --bed-border: #6A1B9A; }

.bed-cell {
  background-color: var(--bed-bg);
  border: 2px solid var(--bed-border);
  border-radius: 4px;
  padding: 8px;
  cursor: pointer;
  min-height: 80px;
  display: flex;
  flex-direction: column;
  gap: 4px;

  &--skeleton {
    animation: pulse 1.5s ease-in-out infinite;
    background-color: #E0E0E0;
    border-color: #BDBDBD;
  }

  &__id      { font-weight: 600; font-size: 0.875rem; }
  &__patient { font-size: 0.75rem; color: #424242; }
  &__discharge { font-size: 0.75rem; color: #616161; margin-top: auto; }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

// Narrow viewport: switch to single-column list view below 1024px.
@media (max-width: 1023px) {
  .bed-board__grid {
    grid-template-columns: 1fr;
  }
}
```

### File: `src/app/features/beds/beds.routes.ts`

```typescript
import { Routes } from '@angular/router';
import { AuthGuard } from '@core/auth/auth.guard';

export const BEDS_ROUTES: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./components/bed-board/bed-board.component').then(m => m.BedBoardComponent),
    canActivate: [AuthGuard],
    data: { roles: ['bed_manager', 'charge_nurse', 'physician', 'admin'] },
  },
];
```

---

## Files Created

| File | Action |
|------|--------|
| `src/app/features/beds/models/bed.model.ts` | **Create** |
| `src/app/features/beds/services/bed-board.service.ts` | **Create** |
| `src/app/features/beds/components/bed-board/bed-board.component.ts` | **Create** |
| `src/app/features/beds/components/bed-board/bed-board.component.html` | **Create** |
| `src/app/features/beds/components/bed-board/bed-board.component.scss` | **Create** |
| `src/app/features/beds/components/bed-cell/bed-cell.component.ts` | **Create** |
| `src/app/features/beds/components/bed-cell/bed-cell.component.html` | **Create** |
| `src/app/shared/pipes/mask-name.pipe.ts` | **Create** |
| `src/app/features/beds/beds.routes.ts` | **Create** |

## Files Modified

| File | Change |
|------|--------|
| `src/app/app.routes.ts` | Add lazy route: `{ path: 'beds', loadChildren: () => import('./features/beds/beds.routes').then(m => m.BEDS_ROUTES) }` |

---

## Validation Checklist

- [ ] `ng build` compiles without TypeScript errors
- [ ] Storybook / dev server renders all 5 `BedStatus` colours on mock data
- [ ] Skeleton loader displays for first 500ms before data resolves (dev tools throttle)
- [ ] `MaskNamePipe` transforms `"John Doe"` → `"J.D."`, `"Mary Jane Watson"` → `"M.J.W."`
- [ ] Null `predictedDischargeTime` shows `—` in cell
- [ ] Grid reflows correctly at 1024px, 1440px, 2560px viewport widths
